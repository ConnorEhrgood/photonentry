#define _GNU_SOURCE
#include "link.h"

#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "../../vendor/cjson/cJSON.h"
#include "apply.h"
#include "http.h"
#include "queue.h"
#include "sign.h"
#include "util.h"
#include "vapix.h"

#define APP_VERSION "0.1.0"
#define EVENTS_PER_SYNC 200
#define FETCH_LIMIT 200
#define DONE_RING 64
#define RETRY_FAILED_S 60
#define REAPPLY_S 3600
#define INVENTORY_S 600

enum { SYNC_OK = 0, SYNC_NETWORK = -1, SYNC_PENDING = 1, SYNC_DISABLED = 2, SYNC_REFUSED = 3 };

static volatile sig_atomic_t stopping = 0;
static void on_signal(int sig) { (void)sig; stopping = 1; }

typedef struct {
    const link_config *cfg;
    EVP_PKEY *key;
    char pub[64], kid[17], claim[10];
    pthread_mutex_t mu;
    int claimed;
    /* persisted in state.json */
    long last_rowid, next_seq, applied_version, failed_version;
    char apply_error[1000];
    time_t failed_at, applied_at;
    /* settings.json: the newest settings received, {"version", "document"} */
    cJSON *settings;
    event_queue queue;
    cJSON *results;                      /* command results not yet delivered */
    char done_ids[DONE_RING][48];        /* commands already carried out (the cloud may hand one out twice) */
    int done_next;
    char *inventory_sent;                /* the inventory as last delivered */
    cJSON *inventory;                    /* the inventory as last read */
    time_t inventory_at, started;
} link_state;

/* -- state on disk --------------------------------------------------------------------------------------------------------------------------- */

static void save_state(link_state *s) {
    cJSON *o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "last_rowid", (double)s->last_rowid);
    cJSON_AddNumberToObject(o, "next_seq", (double)s->next_seq);
    cJSON_AddNumberToObject(o, "applied_version", (double)s->applied_version);
    cJSON_AddNumberToObject(o, "failed_version", (double)s->failed_version);
    cJSON_AddStringToObject(o, "apply_error", s->apply_error);
    cJSON_AddStringToObject(o, "claim_code", s->claim);
    char *text = cJSON_Print(o);
    char path[1024];
    path_join(path, sizeof path, s->cfg->state_dir, "state.json");
    if (write_file_atomic(path, text, strlen(text), 0600) != 0) LOG_ERR("cannot write %s", path);
    free(text);
    cJSON_Delete(o);
}

static long num(const cJSON *o, const char *k, long dflt) {
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(o, k);
    return cJSON_IsNumber(v) ? (long)v->valuedouble : dflt;
}

static void load_state(link_state *s) {
    char path[1024];
    path_join(path, sizeof path, s->cfg->state_dir, "state.json");
    char *text = read_file(path, NULL);
    cJSON *o = text ? cJSON_Parse(text) : NULL;
    free(text);
    s->last_rowid = num(o, "last_rowid", 0);
    s->next_seq = num(o, "next_seq", 1);
    s->applied_version = num(o, "applied_version", 0);
    s->failed_version = num(o, "failed_version", 0);
    const cJSON *e = cJSON_GetObjectItemCaseSensitive(o, "apply_error");
    snprintf(s->apply_error, sizeof s->apply_error, "%s", cJSON_IsString(e) ? e->valuestring : "");
    const cJSON *c = cJSON_GetObjectItemCaseSensitive(o, "claim_code");
    if (cJSON_IsString(c) && strlen(c->valuestring) == 9) snprintf(s->claim, sizeof s->claim, "%s", c->valuestring);
    else claim_code_new(s->claim);
    cJSON_Delete(o);
    /* Events queued but not acknowledged keep their numbers; new ones continue after the highest. */
    const cJSON *ev;
    cJSON_ArrayForEach(ev, s->queue.events) if (num(ev, "seq", 0) >= s->next_seq) s->next_seq = num(ev, "seq", 0) + 1;

    path_join(path, sizeof path, s->cfg->state_dir, "settings.json");
    text = read_file(path, NULL);
    s->settings = text ? cJSON_Parse(text) : NULL;
    free(text);
}

static void save_settings(link_state *s) {
    char *text = cJSON_PrintUnformatted(s->settings);
    char path[1024];
    path_join(path, sizeof path, s->cfg->state_dir, "settings.json");
    if (write_file_atomic(path, text, strlen(text), 0600) != 0) LOG_ERR("cannot write %s", path);
    free(text);
}

/* -- signed requests --------------------------------------------------------------------------------------------------------------------- */

static http_result post(link_state *s, http_client *http, const char *path, const char *body, long timeout_s) {
    char header[300], line[340], url[512];
    if (sign_request(s->key, (long)time(NULL), NULL, "POST", path, body, strlen(body), header, sizeof header) != 0) {
        http_result r;
        memset(&r, 0, sizeof r);
        snprintf(r.error, sizeof r.error, "cannot sign the request");
        r.body = calloc(1, 1);
        return r;
    }
    snprintf(line, sizeof line, "X-PhotonEntry-Link: %s", header);
    snprintf(url, sizeof url, "%s%s", s->cfg->cloud, path);
    return http_post_json(http, url, body, strlen(body), NULL, NULL, line, timeout_s);
}

static int hello(link_state *s, http_client *http) {
    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "public_key", s->pub);
    cJSON_AddStringToObject(req, "claim_code", s->claim);
    cJSON *dev = cJSON_AddObjectToObject(req, "device");
    cJSON_AddStringToObject(dev, "model", s->cfg->model);
    cJSON_AddStringToObject(dev, "serial", s->cfg->serial);
    cJSON_AddStringToObject(dev, "firmware", s->cfg->firmware);
    cJSON_AddStringToObject(dev, "app_version", APP_VERSION);
    char *body = cJSON_PrintUnformatted(req);
    cJSON_Delete(req);
    http_result r = post(s, http, "/link/v1/hello", body, 30);
    free(body);
    int rc = SYNC_NETWORK;
    cJSON *out = r.status == 200 ? cJSON_Parse(r.body) : NULL;
    const cJSON *st = cJSON_GetObjectItemCaseSensitive(out, "state");
    if (cJSON_IsString(st)) {
        rc = strcmp(st->valuestring, "claimed") == 0 ? SYNC_OK : strcmp(st->valuestring, "disabled") == 0 ? SYNC_DISABLED : SYNC_PENDING;
    } else if (r.status) {
        LOG_WARN("hello refused: HTTP %ld", r.status);
        rc = SYNC_REFUSED;
    } else {
        LOG_WARN("hello failed: %s", r.error);
    }
    cJSON_Delete(out);
    http_result_free(&r);
    return rc;
}

/* -- commands and settings ------------------------------------------------------------------------------------------------------------------ */

static void add_result(link_state *s, const char *id, int ok, const char *error) {
    cJSON *r = cJSON_CreateObject();
    cJSON_AddStringToObject(r, "id", id);
    cJSON_AddBoolToObject(r, "ok", ok);
    if (error && error[0]) cJSON_AddStringToObject(r, "error", error);
    cJSON_AddItemToArray(s->results, r);
}

static void run_command(link_state *s, vapix *v, const cJSON *cmd) {
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(cmd, "id");
    const cJSON *kind = cJSON_GetObjectItemCaseSensitive(cmd, "kind");
    const cJSON *door = cJSON_GetObjectItemCaseSensitive(cmd, "door");
    const cJSON *exp = cJSON_GetObjectItemCaseSensitive(cmd, "expires_at");
    if (!cJSON_IsString(id) || !cJSON_IsString(kind) || !cJSON_IsString(door) || !cJSON_IsString(exp)) return;
    for (int i = 0; i < DONE_RING; i++) if (strcmp(s->done_ids[i], id->valuestring) == 0) return;   /* already carried out and reported */
    snprintf(s->done_ids[s->done_next], sizeof s->done_ids[0], "%s", id->valuestring);
    s->done_next = (s->done_next + 1) % DONE_RING;

    time_t expires = parse_iso_utc(exp->valuestring);
    if (expires < 0 || time(NULL) >= expires) {
        LOG_WARN("command %s (%s) arrived after it expired; not carried out", id->valuestring, kind->valuestring);
        add_result(s, id->valuestring, 0, "expired before it arrived");
        return;
    }
    static const struct { const char *kind, *method; } MAP[] = {
        {"access", "tdc:AccessDoor"}, {"lock", "tdc:LockDoor"}, {"unlock", "tdc:UnlockDoor"},
        {"lockdown", "tdc:LockDownDoor"}, {"lockdown_release", "tdc:LockDownReleaseDoor"},
    };
    const char *method = NULL;
    for (size_t i = 0; i < sizeof MAP / sizeof MAP[0]; i++) if (strcmp(MAP[i].kind, kind->valuestring) == 0) method = MAP[i].method;
    if (!method) {
        add_result(s, id->valuestring, 0, "unknown command");
        return;
    }
    cJSON *msg = cJSON_CreateObject();
    cJSON_AddStringToObject(msg, "Token", door->valuestring);
    cJSON *out = vapix_call(v, "doorcontrol", method, msg);
    LOG_INFO("command %s: %s on %s: %s", id->valuestring, kind->valuestring, door->valuestring, out ? "done" : v->fault);
    add_result(s, id->valuestring, out != NULL, out ? "" : v->fault);
    cJSON_Delete(out);
}

/* Apply s->settings. Called with the lock held. */
static void apply_held(link_state *s, vapix *v) {
    long version = num(s->settings, "version", 0);
    const cJSON *doc = cJSON_GetObjectItemCaseSensitive(s->settings, "document");
    apply_stats st;
    if (apply_settings(v, doc, &st) == 0) {
        if (version != s->applied_version || st.set || st.removed || st.doors) {
            LOG_INFO("settings version %ld applied: %d set, %d removed, %d doors", version, st.set, st.removed, st.doors);
        }
        s->applied_version = version;
        s->failed_version = 0;
        s->apply_error[0] = '\0';
        s->inventory_at = 0;                /* read the inventory again: a door may have been renamed */
    } else {
        LOG_ERR("settings version %ld not applied: %s", version, v->fault);
        s->failed_version = version;
        snprintf(s->apply_error, sizeof s->apply_error, "%s", v->fault);
        s->failed_at = time(NULL);
    }
    s->applied_at = time(NULL);
    save_state(s);
}

static void handle_reply(link_state *s, vapix *v, const cJSON *reply) {
    queue_ack(&s->queue, num(reply, "ack_seq", 0));
    const cJSON *settings = cJSON_GetObjectItemCaseSensitive(reply, "settings");
    if (cJSON_IsObject(settings) && num(settings, "version", 0) != s->applied_version) {
        cJSON_Delete(s->settings);
        s->settings = cJSON_Duplicate(settings, 1);
        save_settings(s);
        apply_held(s, v);
    }
    const cJSON *cmd;
    cJSON_ArrayForEach(cmd, cJSON_GetObjectItemCaseSensitive(reply, "commands")) run_command(s, v, cmd);
}

/* -- sync ---------------------------------------------------------------------------------------------------------------------------------- */

static int sync_once(link_state *s, http_client *http, vapix *v, int wait, int with_events) {
    pthread_mutex_lock(&s->mu);
    cJSON *req = cJSON_CreateObject();
    cJSON_AddNumberToObject(req, "applied_version", (double)s->applied_version);
    if (s->failed_version) {
        cJSON_AddNumberToObject(req, "failed_version", (double)s->failed_version);
        cJSON_AddStringToObject(req, "apply_error", s->apply_error);
    }
    char *inventory_text = NULL;
    if (s->inventory) {
        inventory_text = cJSON_PrintUnformatted(s->inventory);
        if (s->inventory_sent && strcmp(inventory_text, s->inventory_sent) == 0) {
            free(inventory_text);
            inventory_text = NULL;
        } else {
            cJSON_AddItemToObject(req, "inventory", cJSON_Duplicate(s->inventory, 1));
        }
    }
    int sent_events = 0;
    if (with_events) {
        cJSON *events = queue_head(&s->queue, EVENTS_PER_SYNC);
        sent_events = cJSON_GetArraySize(events);
        cJSON_AddItemToObject(req, "events", events);
    }
    cJSON *results = s->results;
    s->results = cJSON_CreateArray();
    cJSON_AddItemReferenceToObject(req, "results", results);
    cJSON *health = cJSON_AddObjectToObject(req, "health");
    cJSON_AddNumberToObject(health, "uptime_s", (double)(time(NULL) - s->started));
    cJSON_AddNumberToObject(health, "queued_events", queue_size(&s->queue));
    char clock[32];
    now_iso(clock, sizeof clock);
    cJSON_AddStringToObject(health, "clock", clock);
    cJSON_AddBoolToObject(req, "wait", wait && sent_events == 0);
    char *body = cJSON_PrintUnformatted(req);
    cJSON_Delete(req);
    pthread_mutex_unlock(&s->mu);

    http_result r = post(s, http, "/link/v1/sync", body, wait ? 60 : 30);
    free(body);
    cJSON *reply = cJSON_Parse(r.body);
    int rc = SYNC_OK;

    pthread_mutex_lock(&s->mu);
    if (r.status == 200 && cJSON_IsObject(reply)) {
        cJSON_Delete(results);
        if (inventory_text) {
            free(s->inventory_sent);
            s->inventory_sent = inventory_text;
            inventory_text = NULL;
        }
        handle_reply(s, v, reply);
    } else {
        /* Not delivered: the results go back in front of anything added meanwhile. */
        cJSON *item;
        while ((item = cJSON_DetachItemFromArray(s->results, 0)) != NULL) cJSON_AddItemToArray(results, item);
        cJSON_Delete(s->results);
        s->results = results;
        const cJSON *st = cJSON_GetObjectItemCaseSensitive(reply, "state");
        if (r.status == 403 && cJSON_IsString(st)) {
            rc = strcmp(st->valuestring, "disabled") == 0 ? SYNC_DISABLED : SYNC_PENDING;
            s->claimed = 0;
        } else if (r.status == 401) {
            rc = SYNC_PENDING;                  /* the cloud does not know our key (any more): introduce ourselves again */
            s->claimed = 0;
        } else if (r.status) {
            LOG_WARN("sync refused: HTTP %ld", r.status);
            rc = SYNC_REFUSED;
        } else {
            rc = SYNC_NETWORK;
        }
    }
    pthread_mutex_unlock(&s->mu);
    free(inventory_text);
    cJSON_Delete(reply);
    http_result_free(&r);
    return rc;
}

/* -- reading the controller's events -------------------------------------------------------------------------------------------------------- */

static cJSON *convert_event(const cJSON *row, long seq) {
    cJSON *ev = cJSON_CreateObject();
    cJSON_AddNumberToObject(ev, "seq", (double)seq);
    const cJSON *t = cJSON_GetObjectItemCaseSensitive(row, "UtcTime");
    cJSON_AddStringToObject(ev, "occurred_at", cJSON_IsString(t) ? t->valuestring : "1970-01-01T00:00:00Z");
    char topic[200] = "";
    const char *parts[4] = {0};
    cJSON *source = cJSON_CreateObject(), *data = cJSON_CreateObject();
    const cJSON *kv;
    cJSON_ArrayForEach(kv, cJSON_GetObjectItemCaseSensitive(row, "KeyValues")) {
        const cJSON *k = cJSON_GetObjectItemCaseSensitive(kv, "Key"), *val = cJSON_GetObjectItemCaseSensitive(kv, "Value");
        if (!cJSON_IsString(k) || !cJSON_IsString(val)) continue;
        if (strncmp(k->valuestring, "topic", 5) == 0 && k->valuestring[5] >= '0' && k->valuestring[5] <= '3' && !k->valuestring[6]) {
            parts[k->valuestring[5] - '0'] = val->valuestring;
            continue;
        }
        int is_source = 0;
        const cJSON *tag;
        cJSON_ArrayForEach(tag, cJSON_GetObjectItemCaseSensitive(kv, "Tags"))
            if (cJSON_IsString(tag) && strcmp(tag->valuestring, "onvif-source") == 0) is_source = 1;
        cJSON_AddStringToObject(is_source ? source : data, k->valuestring, val->valuestring);
    }
    for (int i = 0; i < 4 && parts[i]; i++) {
        if (i) strncat(topic, "/", sizeof topic - strlen(topic) - 1);
        strncat(topic, parts[i], sizeof topic - strlen(topic) - 1);
    }
    cJSON_AddStringToObject(ev, "topic", topic);
    cJSON_AddItemToObject(ev, "source", source);
    cJSON_AddItemToObject(ev, "data", data);
    const cJSON *tok = cJSON_GetObjectItemCaseSensitive(row, "token");
    cJSON_AddStringToObject(ev, "ref", cJSON_IsString(tok) ? tok->valuestring : "");
    return ev;
}

/* Read new rows from the controller's event log into the queue. Returns the number queued, or -1 if the controller did not answer. */
static int read_events(link_state *s, vapix *v) {
    int queued = 0;
    while (!stopping) {
        pthread_mutex_lock(&s->mu);
        int room = QUEUE_CAP - queue_size(&s->queue);
        long after = s->last_rowid;
        pthread_mutex_unlock(&s->mu);
        if (room <= 0) return queued;              /* the controller's own log holds the rest until there is room */
        cJSON *msg = cJSON_CreateObject();
        cJSON_AddNumberToObject(msg, "RowID", (double)after);
        cJSON_AddNumberToObject(msg, "Limit", room < FETCH_LIMIT ? room : FETCH_LIMIT);
        cJSON *out = vapix_call(v, "eventlogger", "axlog:FetchEvents", msg);
        if (!out) return -1;
        const cJSON *rows = cJSON_GetObjectItemCaseSensitive(out, "Event");
        int n = cJSON_GetArraySize(rows);
        if (n == 0 && after > 0) {
            /* Nothing after our cursor. If the controller's newest row is older than the cursor its log was reset (a factory default): start over. */
            cJSON *m2 = cJSON_CreateObject();
            cJSON_AddBoolToObject(m2, "Descending", 1);
            cJSON_AddNumberToObject(m2, "Limit", 1);
            cJSON *latest = vapix_call(v, "eventlogger", "axlog:FetchEvents", m2);
            long newest = num(cJSON_GetArrayItem(cJSON_GetObjectItemCaseSensitive(latest, "Event"), 0), "rowid", 0);
            cJSON_Delete(latest);
            if (latest && newest < after) {
                LOG_WARN("the controller's event log restarted (newest row %ld, cursor %ld); reading from the start", newest, after);
                pthread_mutex_lock(&s->mu);
                s->last_rowid = 0;
                save_state(s);
                pthread_mutex_unlock(&s->mu);
                cJSON_Delete(out);
                continue;
            }
        }
        pthread_mutex_lock(&s->mu);
        const cJSON *row;
        cJSON_ArrayForEach(row, rows) {
            if (queue_push(&s->queue, convert_event(row, s->next_seq)) != 0) break;
            s->next_seq++;
            s->last_rowid = num(row, "rowid", s->last_rowid);
            queued++;
        }
        save_state(s);
        pthread_mutex_unlock(&s->mu);
        const cJSON *more = cJSON_GetObjectItemCaseSensitive(out, "More");
        int again = cJSON_IsTrue(more);
        cJSON_Delete(out);
        if (!again) return queued;
    }
    return queued;
}

/* -- threads ----------------------------------------------------------------------------------------------------------------------------------- */

static void nap_ms(int ms) {
    struct timespec ts = {ms / 1000, (long)(ms % 1000) * 1000000L};
    while (!stopping && nanosleep(&ts, &ts) != 0 && errno == EINTR) {}
}

static void *events_thread(void *arg) {
    link_state *s = arg;
    http_client *http = http_client_new();
    vapix v = {s->cfg->vapix_base, s->cfg->vapix_user, s->cfg->vapix_pass, http_client_new(), ""};
    int backoff = 0;
    while (!stopping) {
        pthread_mutex_lock(&s->mu);
        int claimed = s->claimed;
        pthread_mutex_unlock(&s->mu);
        if (claimed) {
            if (read_events(s, &v) < 0) LOG_WARN("cannot read the controller's events: %s", v.fault);
            pthread_mutex_lock(&s->mu);
            int pending = queue_size(&s->queue) > 0 || cJSON_GetArraySize(s->results) > 0;
            pthread_mutex_unlock(&s->mu);
            if (pending && backoff == 0) {
                int rc = sync_once(s, http, &v, 0, 1);
                if (rc == SYNC_NETWORK || rc == SYNC_REFUSED) backoff = 1;
            } else if (backoff) {
                backoff = backoff >= 30 ? 0 : backoff * 2;     /* retry after 1, 2, 4 ... 32 polls */
            }
        }
        nap_ms(s->cfg->event_poll_ms);
    }
    http_client_free(http);
    http_client_free(v.http);
    return NULL;
}

static void *control_thread(void *arg) {
    link_state *s = arg;
    http_client *http = http_client_new();
    vapix v = {s->cfg->vapix_base, s->cfg->vapix_user, s->cfg->vapix_pass, http_client_new(), ""};
    int backoff_s = 1;
    while (!stopping) {
        pthread_mutex_lock(&s->mu);
        int claimed = s->claimed;
        pthread_mutex_unlock(&s->mu);
        if (!claimed) {
            int rc = hello(s, http);
            if (rc == SYNC_OK) {
                LOG_INFO("claimed; linking");
                pthread_mutex_lock(&s->mu);
                s->claimed = 1;
                pthread_mutex_unlock(&s->mu);
                continue;
            }
            if (rc == SYNC_PENDING) LOG_INFO("waiting to be claimed: claim code %s", s->claim);
            if (rc == SYNC_DISABLED) LOG_WARN("this controller is disabled in PhotonEntry");
            for (int i = 0; i < (rc == SYNC_DISABLED ? 60 : 5) && !stopping; i++) nap_ms(1000);
            continue;
        }
        time_t now = time(NULL);
        pthread_mutex_lock(&s->mu);
        int need_inventory = now - s->inventory_at >= INVENTORY_S;
        pthread_mutex_unlock(&s->mu);
        if (need_inventory) {
            cJSON *inv = read_inventory(&v);
            pthread_mutex_lock(&s->mu);
            if (inv) {
                cJSON_Delete(s->inventory);
                s->inventory = inv;
                s->inventory_at = now;
            }
            pthread_mutex_unlock(&s->mu);
            if (!inv) LOG_WARN("cannot read the controller's doors: %s", v.fault);
        }
        pthread_mutex_lock(&s->mu);
        if (s->settings && ((s->failed_version && now - s->failed_at >= RETRY_FAILED_S) || now - s->applied_at >= REAPPLY_S)) {
            apply_held(s, &v);                     /* a retry, or the hourly drift check (apply is a difference: usually nothing to do) */
        }
        pthread_mutex_unlock(&s->mu);
        int rc = sync_once(s, http, &v, 1, 0);
        if (rc == SYNC_NETWORK || rc == SYNC_REFUSED) {
            LOG_WARN("cloud unreachable; retrying in %d s", backoff_s);
            for (int i = 0; i < backoff_s && !stopping; i++) nap_ms(1000);
            backoff_s = backoff_s >= 30 ? 30 : backoff_s * 2;
        } else {
            backoff_s = 1;
        }
    }
    http_client_free(http);
    http_client_free(v.http);
    return NULL;
}

int link_run(const link_config *cfg) {
    link_state *s = calloc(1, sizeof *s);
    s->cfg = cfg;
    pthread_mutex_init(&s->mu, NULL);
    mkdir(cfg->state_dir, 0700);
    s->key = key_load_or_create(cfg->state_dir);
    if (!s->key || key_public(s->key, s->pub, s->kid) != 0) {
        LOG_ERR("no identity key; stopping");
        return 1;
    }
    if (queue_open(&s->queue, cfg->state_dir) != 0) return 1;
    load_state(s);
    save_state(s);
    s->results = cJSON_CreateArray();
    s->started = time(NULL);
    s->applied_at = s->started;                    /* the settings on disk were applied before the restart; drift is checked hourly */
    LOG_INFO("entry-link %s, key %s, claim code %s, %d events queued, settings version %ld", APP_VERSION, s->kid, s->claim,
             queue_size(&s->queue), s->applied_version);

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    pthread_t a, b;
    pthread_create(&a, NULL, control_thread, s);
    pthread_create(&b, NULL, events_thread, s);
    while (!stopping) nap_ms(200);
    /* Everything that matters is on disk already; a held long-poll is simply abandoned. */
    LOG_INFO("stopping");
    return 0;
}
