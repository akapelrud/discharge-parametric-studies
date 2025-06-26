
TOPTARGETS := all clean
SUBDIRS := Vessel/. StreamerIntegralCriterion/.

$(TOPTARGETS): $(SUBDIRS)
$(SUBDIRS):
	$(MAKE) -C $@ $(MAKECMDGOALS)

.PHONY: $(TOPTARGETS) $(SUBDIRS)

