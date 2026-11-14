# Host build of entry-link, for tests against the simulator (sim/). The controller build uses Axis's ACAP Native SDK (Step 7).
CC ?= gcc
CFLAGS ?= -O2 -g
CFLAGS += -std=c11 -Wall -Wextra -Werror -Wno-missing-field-initializers -pthread -D_POSIX_C_SOURCE=200809L
LDLIBS = -lcurl -lcrypto -pthread
SRC = app/main.c app/link.c app/local.c app/apply.c app/vapix.c app/http.c app/queue.c app/sign.c app/util.c ../vendor/cjson/cJSON.c
OBJ = $(patsubst %.c,build/%.o,$(notdir $(SRC)))

build/entry-link: $(SRC) $(wildcard app/*.h)
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ $(SRC) $(LDLIBS)

clean:
	rm -rf build

.PHONY: clean
