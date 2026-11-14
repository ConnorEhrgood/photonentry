/* entry-link's endpoint on the building's network, for the intercoms at its doors (ARCHITECTURE §3.4): an Akuvox "web relay" request opens
 * the door the intercom is at (unlock from a call), and the intercom's action URLs report tamper and calls. It needs no internet.
 *
 * A deliberately small HTTP/1.1 server: GET only, one request per connection, the request head at most LOCAL_MAX_HEAD bytes and read within
 * LOCAL_READ_TIMEOUT_S, one connection at a time. It parses; what a request means is decided by the handler (link.c). */
#ifndef ENTRY_LINK_LOCAL_H
#define ENTRY_LINK_LOCAL_H

#include <signal.h>
#include <stddef.h>

#define LOCAL_MAX_HEAD 4096
#define LOCAL_READ_TIMEOUT_S 3
#define LOCAL_MAX_PARAMS 12

typedef struct {
    char path[256];                  /* without the query, percent-decoded */
    int nparams;
    char keys[LOCAL_MAX_PARAMS][32];
    char values[LOCAL_MAX_PARAMS][128];   /* percent-decoded; a longer value is refused (400), never cut */
    char user[64], pass[128];        /* from Authorization: Basic, when present */
    char peer[64];                   /* the client's address */
} local_request;

typedef struct {
    int status;
    char body[256];
} local_response;

/* The value of query parameter `key`, or NULL. */
const char *local_param(const local_request *r, const char *key);

typedef void (*local_handler)(void *ctx, const local_request *req, local_response *res);

/* Serve on bind_addr:port until *stop becomes nonzero (checked at least every 200 ms). Returns 0, or -1 if the port cannot be opened. */
int local_serve(const char *bind_addr, int port, local_handler handler, void *ctx, volatile sig_atomic_t *stop);

/* Parse one request head (exposed for tests). 0, or the HTTP status to answer with (400, 405, 414, 431). */
int local_parse(const char *head, size_t len, local_request *out);

#endif
