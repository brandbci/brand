export ROOT ?= $(shell pwd)
include $(ROOT)/setenv.mk

# Get all directories in nodes/ and derivatives/
SUBDIRS_NODES=$(wildcard nodes/*)
SUBDIRS_DERIVS=$(wildcard derivatives/*)

# make some clean targets for all subdirs
CLEANDIRS_NODES = $(SUBDIRS_NODES:%=clean-%)
CLEANDIRS_DERIVS = $(SUBDIRS_DERIVS:%=clean-%)

# Get all directories in ../brand-modules/*/nodes/ and ../brand-modules/*/derivatives/
MODULES_BASE_PATH=../brand-modules
MODULES_NODES=$(wildcard $(MODULES_BASE_PATH)/*/nodes/*)
MODULES_DERIVS=$(wildcard $(MODULES_BASE_PATH)/*/derivatives/*)

# make some clean targets for all subdirs
MODULES_CLEANDIRS_NODES = $(MODULES_NODES:%=clean-%)
MODULES_CLEANDIRS_DERIVS = $(MODULES_DERIVS:%=clean-%)

all: $(SUBDIRS_NODES) $(SUBDIRS_DERIVS) $(MODULES_NODES) $(MODULES_DERIVS) hiredis redis

.PHONY: subdirs $(SUBDIRS_NODES)
.PHONY: subdirs $(SUBDIRS_DERIVS)
.PHONY: subdirs $(CLEANDIRS_NODES)
.PHONY: subdirs $(CLEANDIRS_DERIVS)
.PHONY: modules $(MODULES_NODES)
.PHONY: modules $(MODULES_DERIVS)
.PHONY: modules $(MODULES_CLEANDIRS_NODES)
.PHONY: modules $(MODULES_CLEANDIRS_DERIVS)

# function that tests if a path $(1) is in a Git repository, and writes the Git hash to git_hash.o if so
write_git_hash = @\
	git -C $(1) rev-parse; \
	if [ $$? = 0 ]; then \
		test -s $(1)/git_hash.o; \
		if [ $$? = 0 ]; then \
			rm -f $(1)/git_hash.o; \
		fi; \
		echo -n $$(git -C $(1) rev-parse HEAD) > $(1)/git_hash.o; \
	fi

# function that tests if a Makefile exists in a path $(1), and runs make if so
test_and_make = @\
	test -s $(1)/Makefile; \
	if [ $$? = 0 ]; then \
		test -s $(1)/$$(basename $(1)).bin; \
		if [ $$? = 0 ]; then \
			rm -f $(1)/$$(basename $(1)).bin; \
		fi; \
		$(MAKE) -C $(1); \
	fi

# make targets for all paths under nodes/
$(SUBDIRS_NODES): hiredis redis
	$(call write_git_hash,$@)
	$(call test_and_make,$@)

# make targets for all paths under derivatives/
$(SUBDIRS_DERIVS): hiredis redis
	$(call write_git_hash,$@)
	$(call test_and_make,$@)

# make targets for all relevant paths under ../brand-modules/*/nodes/
$(MODULES_NODES): hiredis redis
	$(call write_git_hash,$@)
	$(call test_and_make,$@)

# make targets for all relevant paths under ../brand-modules/*/derivatives/
$(MODULES_DERIVS): hiredis redis
	$(call write_git_hash,$@)
	$(call test_and_make,$@)

# Linking to hiredis seems to have a bug, where make
# attempt to link to an so filename with the full ver.
# ldconfig to automatically creates that file, and
# a tmp cache is specified to avoid requiring root perms.
hiredis: redis
	$(MAKE) -C $(HIREDIS_PATH)
	ldconfig -C /tmp/cache $(HIREDIS_PATH)
	$(RM) /tmp/cache

redis:
	$(MAKE) -C $(REDIS_PATH) redis-server redis-cli
	mv -f $(REDIS_PATH)/src/redis-server $(BIN_PATH)
	mv -f $(REDIS_PATH)/src/redis-cli $(BIN_PATH)

redis-test:
	$(MAKE) -C $(REDIS_PATH) test

clean-all: clean clean-hiredis

clean: $(CLEANDIRS_NODES) $(CLEANDIRS_DERIVS) $(MODULES_CLEANDIRS_NODES) $(MODULES_CLEANDIRS_DERIVS)

$(CLEANDIRS_NODES):
	$(MAKE) -C $(@:clean-%=%) clean

$(CLEANDIRS_DERIVS):
	$(MAKE) -C $(@:clean-%=%) clean

$(MODULES_CLEANDIRS_NODES):
	$(MAKE) -C $(@:clean-%=%) clean

$(MODULES_CLEANDIRS_DERIVS):
	$(MAKE) -C $(@:clean-%=%) clean

clean-hiredis:
	$(MAKE) -C $(HIREDIS_PATH) clean
	$(RM) $(HIREDIS_PATH)/*.so*

clean-redis:
	$(MAKE) -C $(REDIS_PATH) clean
	$(RM) $(BIN_PATH)/redis-server $(BIN_PATH)/redis-cli

