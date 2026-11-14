#define _GNU_SOURCE
#include "local.h"

#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <netinet/in.h>
#include <openssl/evp.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#include "util.h"

const char *local_param(const local_request *r, const char *key) {
    for (int i = 0; i < r->nparams; i++) if (strcmp(r->keys[i], key) == 0) return r->values[i];
    return NULL;
}

static int hexval(int c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

/* Percent-decode src[0..n) into out (with '+' as a space when `plus`). -1 if it does not fit or is malformed or holds a NUL. */
static int decode(const char *src, size_t n, char *out, size_t size, int plus) {
    size_t o = 0;
    for (size_t i = 0; i < n; i++) {
        int c = (unsigned char)src[i];
        if (c == '%') {
            if (i + 2 >= n) return -1;
            int h = hexval(src[i + 1]), l = hexval(src[i + 2]);
            if (h < 0 || l < 0) return -1;
            c = h * 16 + l;
            if (c == 0) return -1;
            i += 2;
        } else if (c == '+' && plus) {
            c = ' ';
        }
        if (o + 1 >= size) return -1;
        out[o++] = (char)c;
    }
    out[o] = '\0';
    return 0;
}

static int parse_query(const char *q, size_t n, local_request *out) {
    size_t i = 0;
    while (i < n) {
        size_t end = i;
        while (end < n && q[end] != '&') end++;
        if (end > i) {
            if (out->nparams >= LOCAL_MAX_PARAMS) return 400;
            size_t eq = i;
            while (eq < end && q[eq] != '=') eq++;
            int k = out->nparams;
            if (decode(q + i, eq - i, out->keys[k], sizeof out->keys[k], 1) != 0) return 400;
            out->values[k][0] = '\0';
            if (eq < end && decode(q + eq + 1, end - eq - 1, out->values[k], sizeof out->values[k], 1) != 0) return 400;
            out->nparams++;
        }
        i = end + 1;
    }
    return 0;
}

/* Authorization: Basic <base64(user:pass)>. Anything else is ignored (no credentials). */
static void parse_basic(const char *v, size_t n, local_request *out) {
    while (n && (*v == ' ' || *v == '\t')) { v++; n--; }
    if (n < 6 || strncasecmp(v, "Basic ", 6) != 0) return;
    v += 6; n -= 6;
    while (n && (v[n - 1] == ' ' || v[n - 1] == '\t')) n--;
    unsigned char buf[256];
    if (n == 0 || n % 4 || n > 4 * (sizeof buf / 3) - 4) return;
    int len = EVP_DecodeBlock(buf, (const unsigned char *)v, (int)n);
    if (len < 0) return;
    while (n && v[n - 1] == '=') { n--; len--; }      /* EVP_DecodeBlock counts the padding as zero bytes */
    if (len <= 0) return;
    buf[len] = '\0';
    if (memchr(buf, '\0', (size_t)len)) return;
    char *colon = strchr((char *)buf, ':');
    if (!colon || (size_t)(colon - (char *)buf) >= sizeof out->user || strlen(colon + 1) >= sizeof out->pass) return;
    size_t ulen = (size_t)(colon - (char *)buf), plen = strlen(colon + 1);
    memcpy(out->user, buf, ulen);                  /* both lengths checked above */
    out->user[ulen] = '\0';
    memcpy(out->pass, colon + 1, plen + 1);
}

int local_parse(const char *head, size_t len, local_request *out) {
    memset(out, 0, sizeof *out);
    const char *eol = memmem(head, len, "\r\n", 2);
    if (!eol) return 400;
    size_t line = (size_t)(eol - head);
    if (line < 4 || memcmp(head, "GET ", 4) != 0) {
        const char *sp = memchr(head, ' ', line);
        return sp && sp > head ? 405 : 400;
    }
    const char *target = head + 4;
    const char *sp = memchr(target, ' ', line - 4);
    if (!sp || (size_t)(eol - sp) < 9 || memcmp(sp + 1, "HTTP/1.", 7) != 0) return 400;
    size_t tlen = (size_t)(sp - target);
    if (tlen == 0 || target[0] != '/') return 400;
    const char *qm = memchr(target, '?', tlen);
    size_t plen = qm ? (size_t)(qm - target) : tlen;
    if (decode(target, plen, out->path, sizeof out->path, 0) != 0) return 414;
    if (qm) {
        int rc = parse_query(qm + 1, tlen - plen - 1, out);
        if (rc) return rc;
    }
    /* Headers: only Authorization matters. */
    const char *p = eol + 2, *end = head + len;
    while (p < end) {
        const char *e = memmem(p, (size_t)(end - p), "\r\n", 2);
        if (!e || e == p) break;
        const char *colon = memchr(p, ':', (size_t)(e - p));
        if (colon && (size_t)(colon - p) == 13 && strncasecmp(p, "Authorization", 13) == 0) parse_basic(colon + 1, (size_t)(e - colon - 1), out);
        p = e + 2;
    }
    return 0;
}

static const char *reason(int status) {
    switch (status) {
        case 200: return "OK";
        case 400: return "Bad Request";
        case 401: return "Unauthorized";
        case 404: return "Not Found";
        case 405: return "Method Not Allowed";
        case 408: return "Request Timeout";
        case 414: return "URI Too Long";
        case 429: return "Too Many Requests";
        case 431: return "Request Header Fields Too Large";
        case 503: return "Service Unavailable";
        default: return "Error";
    }
}

static void respond(int fd, int status, const char *body) {
    char buf[512];
    int n = snprintf(buf, sizeof buf, "HTTP/1.1 %d %s\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: %zu\r\nConnection: close\r\n%s\r\n%s",
                     status, reason(status), strlen(body), status == 401 ? "WWW-Authenticate: Basic realm=\"entry-link\"\r\n" : "", body);
    if (n > 0) {
        ssize_t w = send(fd, buf, (size_t)n < sizeof buf ? (size_t)n : sizeof buf - 1, MSG_NOSIGNAL);
        (void)w;
    }
}

static void serve_one(int fd, const char *peer, local_handler handler, void *ctx) {
    struct timeval tv = {LOCAL_READ_TIMEOUT_S, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
    char head[LOCAL_MAX_HEAD + 1];
    size_t got = 0;
    int status = 0;
    struct timespec start;
    clock_gettime(CLOCK_MONOTONIC, &start);
    for (;;) {
        if (got == LOCAL_MAX_HEAD) { status = 431; break; }
        ssize_t n = recv(fd, head + got, LOCAL_MAX_HEAD - got, 0);
        if (n <= 0) { status = n == 0 ? 400 : 408; break; }
        got += (size_t)n;
        head[got] = '\0';
        if (memmem(head, got, "\r\n\r\n", 4)) break;
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);
        if (now.tv_sec - start.tv_sec >= LOCAL_READ_TIMEOUT_S) { status = 408; break; }   /* a trickle of bytes does not hold the door endpoint */
    }
    local_request req;
    if (!status) status = local_parse(head, got, &req);
    if (status) {
        respond(fd, status, reason(status));
        return;
    }
    snprintf(req.peer, sizeof req.peer, "%s", peer);
    local_response res = {404, "not found"};
    handler(ctx, &req, &res);
    respond(fd, res.status, res.body);
}

int local_serve(const char *bind_addr, int port, local_handler handler, void *ctx, volatile sig_atomic_t *stop) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons((unsigned short)port);
    if (inet_pton(AF_INET, bind_addr, &a.sin_addr) != 1 || bind(fd, (struct sockaddr *)&a, sizeof a) != 0 || listen(fd, 16) != 0) {
        LOG_ERR("cannot open the local endpoint on %s:%d: %s", bind_addr, port, strerror(errno));
        close(fd);
        return -1;
    }
    LOG_INFO("local endpoint for intercoms on %s:%d", bind_addr, port);
    while (!*stop) {
        struct pollfd p = {fd, POLLIN, 0};
        if (poll(&p, 1, 200) <= 0) continue;
        struct sockaddr_in peer;
        socklen_t plen = sizeof peer;
        int c = accept(fd, (struct sockaddr *)&peer, &plen);
        if (c < 0) continue;
        char addr[64] = "";
        inet_ntop(AF_INET, &peer.sin_addr, addr, sizeof addr);
        serve_one(c, addr, handler, ctx);
        close(c);
    }
    close(fd);
    return 0;
}
