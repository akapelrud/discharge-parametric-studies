
TOPTARGETS := all clean
SUBDIRS := studies/DischargeInception/. studies/Plasma/.

$(TOPTARGETS): $(SUBDIRS)
$(SUBDIRS):
	$(MAKE) -C $@ $(MAKECMDGOALS)

.PHONY: $(TOPTARGETS) $(SUBDIRS)

