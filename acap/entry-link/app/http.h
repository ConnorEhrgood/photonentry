/* One HTTP POST with libcurl. Each thread keeps its own handle (libcurl handles are not shared between threads). */
#ifndef ENTRY_LINK_HTTP_H
#define ENTRY_LINK_HTTP_H

#include <stddef.h>

typedef struct {
    long status;          /* HTTP status, or 0 when the request did not complete */
    char *body;           /* NUL-terminated response body (caller frees with http_result_free) */
    size_t len;
    char error[256];      /* libcurl's message when status is 0 */
} http_result;

typedef struct http_client http_client;

http_client *http_client_new(void);
void http_client_free(http_client *c);

/* POST `body` as JSON. `auth_user`/`auth_pass` non-NULL: HTTP authentication (Digest or Basic, whichever the server offers).
 * `extra_header` non-NULL: one more "Name: value" header. `timeout_s`: the whole request. */
http_result http_post_json(http_client *c, const char *url, const char *body, size_t len, const char *auth_user, const char *auth_pass,
                           const char *extra_header, long timeout_s);
void http_result_free(http_result *r);

#endif
