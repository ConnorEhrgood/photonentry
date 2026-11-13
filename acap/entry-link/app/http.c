#include "http.h"

#include <curl/curl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct http_client {
    CURL *curl;
};

http_client *http_client_new(void) {
    http_client *c = calloc(1, sizeof *c);
    if (c) c->curl = curl_easy_init();
    if (c && !c->curl) { free(c); return NULL; }
    return c;
}

void http_client_free(http_client *c) {
    if (!c) return;
    curl_easy_cleanup(c->curl);
    free(c);
}

static size_t collect(char *data, size_t size, size_t n, void *userp) {
    http_result *r = userp;
    size_t add = size * n;
    char *bigger = realloc(r->body, r->len + add + 1);
    if (!bigger) return 0;
    r->body = bigger;
    memcpy(r->body + r->len, data, add);
    r->len += add;
    r->body[r->len] = '\0';
    return add;
}

http_result http_post_json(http_client *c, const char *url, const char *body, size_t len, const char *auth_user, const char *auth_pass,
                           const char *extra_header, long timeout_s) {
    http_result r;
    memset(&r, 0, sizeof r);
    CURL *h = c->curl;
    curl_easy_reset(h);
    struct curl_slist *headers = curl_slist_append(NULL, "Content-Type: application/json");
    if (extra_header) headers = curl_slist_append(headers, extra_header);
    headers = curl_slist_append(headers, "Expect:");
    curl_easy_setopt(h, CURLOPT_URL, url);
    curl_easy_setopt(h, CURLOPT_POST, 1L);
    curl_easy_setopt(h, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(h, CURLOPT_POSTFIELDSIZE, (long)len);
    curl_easy_setopt(h, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(h, CURLOPT_WRITEFUNCTION, collect);
    curl_easy_setopt(h, CURLOPT_WRITEDATA, &r);
    curl_easy_setopt(h, CURLOPT_TIMEOUT, timeout_s);
    curl_easy_setopt(h, CURLOPT_CONNECTTIMEOUT, 10L);
    curl_easy_setopt(h, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(h, CURLOPT_NOPROXY, "127.0.0.1,127.0.0.12,localhost");   /* Axis: 127.0.0.12 must bypass any device proxy */
    if (auth_user) {
        curl_easy_setopt(h, CURLOPT_HTTPAUTH, (long)CURLAUTH_ANY);
        curl_easy_setopt(h, CURLOPT_USERNAME, auth_user);
        curl_easy_setopt(h, CURLOPT_PASSWORD, auth_pass ? auth_pass : "");
    }
    CURLcode rc = curl_easy_perform(h);
    if (rc == CURLE_OK) {
        curl_easy_getinfo(h, CURLINFO_RESPONSE_CODE, &r.status);
    } else {
        snprintf(r.error, sizeof r.error, "%s", curl_easy_strerror(rc));
        r.status = 0;
    }
    if (!r.body) r.body = calloc(1, 1);
    curl_slist_free_all(headers);
    return r;
}

void http_result_free(http_result *r) {
    free(r->body);
    r->body = NULL;
}
