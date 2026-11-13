/* Events read from the controller and not yet acknowledged by the cloud, kept on disk so a restart or a long outage loses nothing.
 *
 * Each event gets the next sequence number when it is read from the controller's log (by row id) and is appended to <dir>/queue.jsonl
 * (fsync'd) before the row id cursor moves on (<dir>/state.json, written atomically). A crash between the two re-reads the same rows on restart
 * and queues them again under new numbers: duplicates are possible, losses are not; the cloud recognizes them by `ref` (the controller's own
 * event token).
 *
 * The queue holds at most QUEUE_CAP events. When it is full, entry-link stops reading the controller, whose own log (30,000 events) keeps the
 * rest until there is room. */
#ifndef ENTRY_LINK_QUEUE_H
#define ENTRY_LINK_QUEUE_H

#include "../../vendor/cjson/cJSON.h"

#define QUEUE_CAP 10000

typedef struct {
    char path[1024];
    cJSON *events;      /* array, oldest first, each with "seq" */
    int dropped_lines;  /* lines of the file that were acknowledged but not yet compacted away */
} event_queue;

int queue_open(event_queue *q, const char *dir);
/* Append (takes ownership of ev, which already has "seq"). 0 on success. */
int queue_push(event_queue *q, cJSON *ev);
/* Remove every event with seq <= ack. */
void queue_ack(event_queue *q, long ack);
int queue_size(const event_queue *q);
/* Copies of the oldest `max` events (caller deletes). */
cJSON *queue_head(const event_queue *q, int max);
void queue_close(event_queue *q);

#endif
