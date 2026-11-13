#define _GNU_SOURCE
#include "util.h"

#include <errno.h>
#include <fcntl.h>
#include <openssl/evp.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifdef ENTRY_LINK_ACAP
#include <syslog.h>
#endif

void el_log(const char *level, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
#ifdef ENTRY_LINK_ACAP
    char line[1024];
    vsnprintf(line, sizeof line, fmt, ap);
    syslog(strcmp(level, "error") == 0 ? LOG_ERR : strcmp(level, "warn") == 0 ? LOG_WARNING : LOG_INFO, "%s", line);
#else
    char when[32];
    now_iso(when, sizeof when);
    fprintf(stderr, "%s entry-link %s: ", when, level);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
#endif
    va_end(ap);
}

char *read_file(const char *path, size_t *len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    size_t cap = 4096, n = 0;
    char *buf = malloc(cap + 1);
    size_t got;
    while (buf && (got = fread(buf + n, 1, cap - n, f)) > 0) {
        n += got;
        if (n == cap) {
            char *bigger = realloc(buf, cap * 2 + 1);
            if (!bigger) { free(buf); buf = NULL; break; }
            buf = bigger;
            cap *= 2;
        }
    }
    fclose(f);
    if (!buf) return NULL;
    buf[n] = '\0';
    if (len) *len = n;
    return buf;
}

int write_file_atomic(const char *path, const char *data, size_t len, int mode) {
    char tmp[1024];
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    int fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, mode);
    if (fd < 0) return -1;
    size_t done = 0;
    while (done < len) {
        ssize_t w = write(fd, data + done, len - done);
        if (w < 0) {
            if (errno == EINTR) continue;
            close(fd);
            unlink(tmp);
            return -1;
        }
        done += (size_t)w;
    }
    if (fsync(fd) != 0 || close(fd) != 0) { unlink(tmp); return -1; }
    return rename(tmp, path);
}

void path_join(char *buf, size_t size, const char *dir, const char *name) { snprintf(buf, size, "%s/%s", dir, name); }

time_t parse_iso_utc(const char *s) {
    struct tm tm;
    memset(&tm, 0, sizeof tm);
    const char *rest = s ? strptime(s, "%Y-%m-%dT%H:%M:%S", &tm) : NULL;
    if (!rest) return -1;
    if (*rest == '.') {
        rest++;
        while (*rest >= '0' && *rest <= '9') rest++;
    }
    if (strcmp(rest, "Z") != 0 && strcmp(rest, "+00:00") != 0) return -1;
    return timegm(&tm);
}

void now_iso(char *buf, size_t size) {
    time_t t = time(NULL);
    struct tm tm;
    gmtime_r(&t, &tm);
    strftime(buf, size, "%Y-%m-%dT%H:%M:%SZ", &tm);
}

void sha256_hex(const unsigned char *data, size_t len, char out[65]) {
    unsigned char md[32];
    unsigned int n = 0;
    EVP_Digest(data, len, md, &n, EVP_sha256(), NULL);
    for (unsigned int i = 0; i < 32; i++) sprintf(out + 2 * i, "%02x", md[i]);
    out[64] = '\0';
}

size_t b64url_encode(const unsigned char *in, size_t len, char *out) {
    static const char tbl[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    size_t o = 0, i = 0;
    for (; i + 2 < len; i += 3) {
        uint32_t v = (uint32_t)in[i] << 16 | (uint32_t)in[i + 1] << 8 | in[i + 2];
        out[o++] = tbl[v >> 18 & 63]; out[o++] = tbl[v >> 12 & 63]; out[o++] = tbl[v >> 6 & 63]; out[o++] = tbl[v & 63];
    }
    if (len - i == 1) {
        uint32_t v = (uint32_t)in[i] << 16;
        out[o++] = tbl[v >> 18 & 63]; out[o++] = tbl[v >> 12 & 63];
    } else if (len - i == 2) {
        uint32_t v = (uint32_t)in[i] << 16 | (uint32_t)in[i + 1] << 8;
        out[o++] = tbl[v >> 18 & 63]; out[o++] = tbl[v >> 12 & 63]; out[o++] = tbl[v >> 6 & 63];
    }
    out[o] = '\0';
    return o;
}
