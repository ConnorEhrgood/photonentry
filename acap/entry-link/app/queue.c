#include "queue.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "util.h"

static long seq_of(const cJSON *ev) {
    const cJSON *s = cJSON_GetObjectItemCaseSensitive(ev, "seq");
    return cJSON_IsNumber(s) ? (long)s->valuedouble : 0;
}

int queue_open(event_queue *q, const char *dir) {
    memset(q, 0, sizeof *q);
    path_join(q->path, sizeof q->path, dir, "queue.jsonl");
    q->events = cJSON_CreateArray();
    char *text = read_file(q->path, NULL);
    if (!text) return 0;
    char *save = NULL;
    for (char *line = strtok_r(text, "\n", &save); line; line = strtok_r(NULL, "\n", &save)) {
        cJSON *ev = cJSON_Parse(line);
        if (cJSON_IsObject(ev) && seq_of(ev) > 0) cJSON_AddItemToArray(q->events, ev);
        else cJSON_Delete(ev);   /* a line torn by a crash mid-append: it was never acknowledged as stored, so it is read again */
    }
    free(text);
    return 0;
}

int queue_push(event_queue *q, cJSON *ev) {
    char *line = cJSON_PrintUnformatted(ev);
    FILE *f = fopen(q->path, "a");
    int ok = f && fprintf(f, "%s\n", line) > 0 && fflush(f) == 0 && fsync(fileno(f)) == 0;
    if (f) fclose(f);
    free(line);
    if (!ok) {
        cJSON_Delete(ev);
        LOG_ERR("cannot append to %s", q->path);
        return -1;
    }
    cJSON_AddItemToArray(q->events, ev);
    return 0;
}

static void compact(event_queue *q) {
    char *out = NULL;
    size_t len = 0;
    FILE *mem = open_memstream(&out, &len);
    const cJSON *ev;
    cJSON_ArrayForEach(ev, q->events) {
        char *line = cJSON_PrintUnformatted(ev);
        fprintf(mem, "%s\n", line);
        free(line);
    }
    fclose(mem);
    if (write_file_atomic(q->path, out, len, 0600) == 0) q->dropped_lines = 0;
    free(out);
}

void queue_ack(event_queue *q, long ack) {
    int removed = 0;
    while (cJSON_GetArraySize(q->events) > 0 && seq_of(cJSON_GetArrayItem(q->events, 0)) <= ack) {
        cJSON_DeleteItemFromArray(q->events, 0);
        removed++;
    }
    q->dropped_lines += removed;
    /* Rewrite the file when it is mostly acknowledged lines, not on every ack (flash wears). */
    if (removed && (cJSON_GetArraySize(q->events) == 0 || q->dropped_lines > 500)) compact(q);
}

int queue_size(const event_queue *q) { return cJSON_GetArraySize(q->events); }

cJSON *queue_head(const event_queue *q, int max) {
    cJSON *out = cJSON_CreateArray();
    const cJSON *ev;
    int n = 0;
    cJSON_ArrayForEach(ev, q->events) {
        if (n++ == max) break;
        cJSON_AddItemToArray(out, cJSON_Duplicate(ev, 1));
    }
    return out;
}

void queue_close(event_queue *q) {
    cJSON_Delete(q->events);
    q->events = NULL;
}
