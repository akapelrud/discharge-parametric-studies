
TOPTARGETS := all clean
SUBDIRS := StreamerIntegralCriterion/. Vessel/.

$(TOPTARGETS): $(SUBDIRS)
$(SUBDIRS):
	$(MAKE) -C $@ $(MAKECMDGOALS)

.PHONY: $(TOPTARGETS) $(SUBDIRS)

