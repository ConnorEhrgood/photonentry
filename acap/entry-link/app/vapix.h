/* The controller's access-control API (VAPIX JSON: POST /vapix/<endpoint> with {"prefix:Method": {...}}; sim/reference/AXIS-PACS.md). */
#ifndef ENTRY_LINK_VAPIX_H
#define ENTRY_LINK_VAPIX_H

#include "../../vendor/cjson/cJSON.h"
#include "http.h"

typedef struct {
    const char *base;      /* http://127.0.0.12 on the controller; the simulator's address in tests */
    const char *user;
    const char *pass;
    http_client *http;
    char fault[512];       /* the last fault or transport error, for logs and apply_error */
} vapix;

/* Call one method. Takes ownership of `msg` (NULL: {}). Returns the response object (caller deletes) or NULL with `fault` set. */
cJSON *vapix_call(vapix *v, const char *endpoint, const char *method, cJSON *msg);

/* Every item of a Get<X>List, following NextStartReference. Returns a JSON array (caller deletes) or NULL. */
cJSON *vapix_list(vapix *v, const char *endpoint, const char *method, const char *key);

#endif
