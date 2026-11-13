#include "sign.h"

#include <openssl/pem.h>
#include <openssl/rand.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#include "util.h"

EVP_PKEY *key_from_seed(const unsigned char seed[32]) {
    return EVP_PKEY_new_raw_private_key(EVP_PKEY_ED25519, NULL, seed, 32);
}

EVP_PKEY *key_load_or_create(const char *dir) {
    char path[1024];
    path_join(path, sizeof path, dir, "link.key");
    FILE *f = fopen(path, "r");
    if (f) {
        EVP_PKEY *key = PEM_read_PrivateKey(f, NULL, NULL, NULL);
        fclose(f);
        if (key && EVP_PKEY_id(key) == EVP_PKEY_ED25519) return key;
        EVP_PKEY_free(key);
        LOG_ERR("%s is not an Ed25519 key; refusing to replace it (remove it to make a new identity)", path);
        return NULL;
    }
    EVP_PKEY *key = NULL;
    EVP_PKEY_CTX *ctx = EVP_PKEY_CTX_new_id(EVP_PKEY_ED25519, NULL);
    if (!ctx || EVP_PKEY_keygen_init(ctx) <= 0 || EVP_PKEY_keygen(ctx, &key) <= 0) {
        EVP_PKEY_CTX_free(ctx);
        return NULL;
    }
    EVP_PKEY_CTX_free(ctx);
    mode_t old = umask(077);
    f = fopen(path, "w");
    umask(old);
    if (!f || !PEM_write_PrivateKey(f, key, NULL, NULL, 0, NULL, NULL)) {
        if (f) fclose(f);
        EVP_PKEY_free(key);
        LOG_ERR("cannot save the new key to %s", path);
        return NULL;
    }
    fclose(f);
    LOG_INFO("made a new identity key in %s", path);
    return key;
}

int key_public(EVP_PKEY *key, char b64[64], char kid[17]) {
    unsigned char pub[32];
    size_t n = sizeof pub;
    if (EVP_PKEY_get_raw_public_key(key, pub, &n) != 1 || n != 32) return -1;
    b64url_encode(pub, n, b64);
    char hex[65];
    sha256_hex(pub, n, hex);
    memcpy(kid, hex, 16);
    kid[16] = '\0';
    return 0;
}

int sign_request(EVP_PKEY *key, long t, const char *nonce, const char *method, const char *path, const char *body, size_t body_len,
                 char *out, size_t out_size) {
    char n[33];
    if (nonce) {
        snprintf(n, sizeof n, "%s", nonce);
    } else {
        unsigned char raw[16];
        if (RAND_bytes(raw, sizeof raw) != 1) return -1;
        for (int i = 0; i < 16; i++) sprintf(n + 2 * i, "%02x", raw[i]);
    }
    char body_hash[65];
    sha256_hex((const unsigned char *)body, body_len, body_hash);
    char msg[2048];
    int len = snprintf(msg, sizeof msg, "photonentry-link-v1\n%ld\n%s\n%s\n%s\n%s", t, n, method, path, body_hash);
    if (len < 0 || (size_t)len >= sizeof msg) return -1;

    unsigned char sig[64];
    size_t sig_len = sizeof sig;
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    int ok = ctx && EVP_DigestSignInit(ctx, NULL, NULL, NULL, key) == 1 &&
             EVP_DigestSign(ctx, sig, &sig_len, (const unsigned char *)msg, (size_t)len) == 1;
    EVP_MD_CTX_free(ctx);
    if (!ok) return -1;

    char pub[64], kid[17], sig64[100];
    if (key_public(key, pub, kid) != 0) return -1;
    b64url_encode(sig, sig_len, sig64);
    len = snprintf(out, out_size, "k=%s,t=%ld,n=%s,v1=%s", kid, t, n, sig64);
    return (len < 0 || (size_t)len >= out_size) ? -1 : 0;
}

void claim_code_new(char out[10]) {
    static const char crockford[] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
    unsigned char raw[8];
    if (RAND_bytes(raw, sizeof raw) != 1) memset(raw, 0, sizeof raw);
    for (int i = 0, o = 0; i < 8; i++) {
        if (i == 4) out[o++] = '-';
        out[o++] = crockford[raw[i] & 31];
    }
    out[9] = '\0';
}
