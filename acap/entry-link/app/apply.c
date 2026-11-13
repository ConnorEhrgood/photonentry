/* Only objects whose token starts with "pe-" belong to PhotonEntry (api/app/compiler/axis.py): they are created, replaced and removed here.
 * Everything else on the controller (Axis's defaults, the doors, access points and readers set up at commissioning) is left alone, except the
 * listed fields of the doors the settings name.
 *
 * Order matters, because the controller checks references when an object is stored: schedules, then access profiles, users, credentials and
 * door schedules are set; then doors; then stale objects are removed in the reverse order (credentials before the profiles they used, door
 * schedules after the doors stopped pointing at them, schedules last). */
#include "apply.h"

#include <stdio.h>
#include <string.h>

#include "util.h"

#define BATCH 100

typedef struct {
    const char *key;         /* in the settings document */
    const char *endpoint;
    const char *kind;        /* Axis object name: Get<kind>List, Set<kind>, Remove<kind> */
    const char *prefix;
} managed;

static const managed KINDS[] = {
    {"schedules", "schedule", "Schedule", "axsch"},
    {"access_profiles", "pacs", "AccessProfile", "pacsaxis"},
    {"users", "pacs", "User", "axudb"},
    {"credentials", "pacs", "Credential", "pacsaxis"},
    {"door_schedules", "doorcontrol", "DoorScheduleConfiguration", "axtdc"},
};
#define NKINDS (sizeof KINDS / sizeof KINDS[0])

static int ours(const cJSON *obj) {
    const cJSON *t = cJSON_GetObjectItemCaseSensitive(obj, "token");
    return cJSON_IsString(t) && strncmp(t->valuestring, "pe-", 3) == 0;
}

static const char *token_of(const cJSON *obj) {
    const cJSON *t = cJSON_GetObjectItemCaseSensitive(obj, "token");
    return cJSON_IsString(t) ? t->valuestring : "";
}

static const cJSON *find(const cJSON *arr, const char *token) {
    const cJSON *it;
    cJSON_ArrayForEach(it, arr) if (strcmp(token_of(it), token) == 0) return it;
    return NULL;
}

/* Every field of `want` equals the same field of `have` (the controller may add fields of its own). */
static int same(const cJSON *want, const cJSON *have) {
    if (!have) return 0;
    const cJSON *f;
    cJSON_ArrayForEach(f, want) {
        const cJSON *h = cJSON_GetObjectItemCaseSensitive(have, f->string);
        if (!h) {
            /* An empty value the controller leaves out is the same as one it never had. */
            if ((cJSON_IsString(f) && f->valuestring[0] == '\0') || (cJSON_IsArray(f) && cJSON_GetArraySize(f) == 0) || cJSON_IsNull(f)) continue;
            return 0;
        }
        if (!cJSON_Compare(f, h, 1)) return 0;
    }
    return 1;
}

static cJSON *list_all(vapix *v, const managed *k) {
    char method[96], key[64];
    snprintf(method, sizeof method, "%s:Get%sList", k->prefix, k->kind);
    snprintf(key, sizeof key, "%s", k->kind);
    return vapix_list(v, k->endpoint, method, key);
}

static int set_batch(vapix *v, const managed *k, cJSON *items) {
    char method[96];
    snprintf(method, sizeof method, "%s:Set%s", k->prefix, k->kind);
    cJSON *msg = cJSON_CreateObject();
    cJSON_AddItemToObject(msg, k->kind, items);
    cJSON *out = vapix_call(v, k->endpoint, method, msg);
    if (!out) return -1;
    cJSON_Delete(out);
    return 0;
}

static int set_changed(vapix *v, const managed *k, const cJSON *desired, const cJSON *current, apply_stats *st) {
    cJSON *batch = cJSON_CreateArray();
    int n = 0;
    const cJSON *want;
    cJSON_ArrayForEach(want, desired) {
        if (same(want, find(current, token_of(want)))) continue;
        cJSON_AddItemToArray(batch, cJSON_Duplicate(want, 1));
        st->set++;
        if (++n == BATCH) {
            if (set_batch(v, k, batch) != 0) return -1;
            batch = cJSON_CreateArray();
            n = 0;
        }
    }
    if (n == 0) { cJSON_Delete(batch); return 0; }
    return set_batch(v, k, batch);
}

static int remove_stale(vapix *v, const managed *k, const cJSON *desired, const cJSON *current, apply_stats *st) {
    char method[96];
    snprintf(method, sizeof method, "%s:Remove%s", k->prefix, k->kind);
    cJSON *tokens = cJSON_CreateArray();
    int n = 0;
    const cJSON *have;
    cJSON_ArrayForEach(have, current) {
        if (!ours(have) || find(desired, token_of(have))) continue;
        cJSON_AddItemToArray(tokens, cJSON_CreateString(token_of(have)));
        st->removed++;
        n++;
    }
    if (n == 0) { cJSON_Delete(tokens); return 0; }
    cJSON *msg = cJSON_CreateObject();
    cJSON_AddItemToObject(msg, "Token", tokens);
    cJSON *out = vapix_call(v, k->endpoint, method, msg);
    if (!out) return -1;
    cJSON_Delete(out);
    return 0;
}

static cJSON *get_one(vapix *v, const char *method, const char *key, const char *token) {
    cJSON *msg = cJSON_CreateObject();
    cJSON *tokens = cJSON_AddArrayToObject(msg, "Token");
    cJSON_AddItemToArray(tokens, cJSON_CreateString(token));
    cJSON *out = vapix_call(v, "doorcontrol", method, msg);
    if (!out) return NULL;
    cJSON *items = cJSON_GetObjectItemCaseSensitive(out, key);
    cJSON *first = cJSON_IsArray(items) && cJSON_GetArraySize(items) > 0 ? cJSON_DetachItemFromArray(items, 0) : NULL;
    cJSON_Delete(out);
    if (!first) snprintf(v->fault, sizeof v->fault, "%s: the controller has no door %s", method, token);
    return first;
}

static int put_one(vapix *v, const char *method, const char *key, cJSON *obj) {
    cJSON *msg = cJSON_CreateObject();
    cJSON *arr = cJSON_AddArrayToObject(msg, key);
    cJSON_AddItemToArray(arr, obj);
    cJSON *out = vapix_call(v, "doorcontrol", method, msg);
    if (!out) return -1;
    cJSON_Delete(out);
    return 0;
}

static int apply_doors(vapix *v, const cJSON *doors, apply_stats *st) {
    static const char *FIELDS[] = {"Name", "AccessTime", "OpenTooLongTime", "PreAlarmTime"};
    const cJSON *want;
    cJSON_ArrayForEach(want, doors) {
        const char *token = token_of(want);
        cJSON *door = get_one(v, "axtdc:GetDoor", "Door", token);
        if (!door) return -1;
        int changed = 0;
        for (size_t i = 0; i < sizeof FIELDS / sizeof FIELDS[0]; i++) {
            const cJSON *w = cJSON_GetObjectItemCaseSensitive(want, FIELDS[i]);
            const cJSON *h = cJSON_GetObjectItemCaseSensitive(door, FIELDS[i]);
            if (w && !(h && cJSON_Compare(w, h, 1))) {
                cJSON_DeleteItemFromObjectCaseSensitive(door, FIELDS[i]);
                cJSON_AddItemToObject(door, FIELDS[i], cJSON_Duplicate(w, 1));
                changed = 1;
            }
        }
        if (changed) {
            if (put_one(v, "axtdc:SetDoor", "Door", door) != 0) return -1;   /* takes ownership */
        } else {
            cJSON_Delete(door);
        }
        cJSON *cfg = get_one(v, "axtdc:GetDoorConfiguration", "DoorConfiguration", token);
        if (!cfg) return -1;
        const cJSON *w = cJSON_GetObjectItemCaseSensitive(want, "DoorScheduleConfiguration");
        const cJSON *h = cJSON_GetObjectItemCaseSensitive(cfg, "DoorScheduleConfiguration");
        const char *wanted = cJSON_IsString(w) ? w->valuestring : "";
        const char *has = cJSON_IsString(h) ? h->valuestring : "";
        /* Only a link PhotonEntry made, or no link, is replaced: a door schedule someone set up by hand is reported, not overwritten. */
        if (strcmp(wanted, has) != 0 && (has[0] == '\0' || strncmp(has, "pe-", 3) == 0)) {
            cJSON_DeleteItemFromObjectCaseSensitive(cfg, "DoorScheduleConfiguration");
            cJSON_AddStringToObject(cfg, "DoorScheduleConfiguration", wanted);
            if (put_one(v, "axtdc:SetDoorConfiguration", "DoorConfiguration", cfg) != 0) return -1;
            changed = 1;
        } else {
            if (strcmp(wanted, has) != 0) LOG_WARN("door %s has a door schedule PhotonEntry did not make (%s); left alone", token, has);
            cJSON_Delete(cfg);
        }
        st->doors += changed;
    }
    return 0;
}

int apply_settings(vapix *v, const cJSON *settings, apply_stats *st) {
    memset(st, 0, sizeof *st);
    const cJSON *format = cJSON_GetObjectItemCaseSensitive(settings, "format");
    if (!cJSON_IsString(format) || strcmp(format->valuestring, "axis-pacs-1") != 0) {
        snprintf(v->fault, sizeof v->fault, "settings format is not axis-pacs-1");
        return -1;
    }
    cJSON *current[NKINDS] = {0};
    int rc = -1;
    for (size_t i = 0; i < NKINDS; i++) {
        current[i] = list_all(v, &KINDS[i]);
        if (!current[i]) goto out;
    }
    for (size_t i = 0; i < NKINDS; i++) {
        const cJSON *desired = cJSON_GetObjectItemCaseSensitive(settings, KINDS[i].key);
        if (!cJSON_IsArray(desired)) {
            snprintf(v->fault, sizeof v->fault, "settings have no %s list", KINDS[i].key);
            goto out;
        }
        if (set_changed(v, &KINDS[i], desired, current[i], st) != 0) goto out;
    }
    if (apply_doors(v, cJSON_GetObjectItemCaseSensitive(settings, "doors"), st) != 0) goto out;
    for (size_t i = NKINDS; i-- > 0;) {
        if (remove_stale(v, &KINDS[i], cJSON_GetObjectItemCaseSensitive(settings, KINDS[i].key), current[i], st) != 0) goto out;
    }
    rc = 0;
out:
    for (size_t i = 0; i < NKINDS; i++) cJSON_Delete(current[i]);
    return rc;
}

cJSON *read_inventory(vapix *v) {
    cJSON *doors = vapix_list(v, "doorcontrol", "axtdc:GetDoorList", "Door");
    cJSON *aps = doors ? vapix_list(v, "pacs", "pacsaxis:GetAccessPointList", "AccessPoint") : NULL;
    if (!aps) { cJSON_Delete(doors); return NULL; }
    cJSON *inv = cJSON_CreateObject();
    cJSON *out = cJSON_AddArrayToObject(inv, "doors");
    const cJSON *d;
    cJSON_ArrayForEach(d, doors) {
        cJSON *item = cJSON_CreateObject();
        cJSON_AddStringToObject(item, "token", token_of(d));
        const cJSON *name = cJSON_GetObjectItemCaseSensitive(d, "Name");
        cJSON_AddStringToObject(item, "name", cJSON_IsString(name) ? name->valuestring : "");
        cJSON *list = cJSON_AddArrayToObject(item, "access_points");
        const cJSON *ap;
        cJSON_ArrayForEach(ap, aps) {
            const cJSON *entity = cJSON_GetObjectItemCaseSensitive(ap, "Entity");
            if (cJSON_IsString(entity) && strcmp(entity->valuestring, token_of(d)) == 0) cJSON_AddItemToArray(list, cJSON_CreateString(token_of(ap)));
        }
        cJSON_AddItemToArray(out, item);
    }
    cJSON_Delete(doors);
    cJSON_Delete(aps);
    return inv;
}
