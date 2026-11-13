/* The controller's identity: an Ed25519 key made here and never sent anywhere, and the signature on every request
 * (the same scheme as api/app/link/signing.py; contract/link/vectors.json is the shared test vector). */
#ifndef ENTRY_LINK_SIGN_H
#define ENTRY_LINK_SIGN_H

#include <openssl/evp.h>
#include <stddef.h>

/* Load the key from <dir>/link.key, or make one and save it (mode 600). NULL on failure. */
EVP_PKEY *key_load_or_create(const char *dir);
/* From a raw 32-byte seed (tests). */
EVP_PKEY *key_from_seed(const unsigned char seed[32]);
/* The raw public key, base64url (no padding), and the key id (first 16 hex digits of sha256 of the raw public key). */
int key_public(EVP_PKEY *key, char b64[64], char kid[17]);

/* The X-PhotonEntry-Link header value for a request. `nonce` NULL: a random one. 0 on success. */
int sign_request(EVP_PKEY *key, long t, const char *nonce, const char *method, const char *path, const char *body, size_t body_len,
                 char *out, size_t out_size);

/* A random claim code, Crockford base32 "XXXX-XXXX". */
void claim_code_new(char out[10]);

#endif
