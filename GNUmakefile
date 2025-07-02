
TOPTARGETS := all clean
SUBDIRS := InceptionStepper/. StreamerIntegralCriterion/.

$(TOPTARGETS): $(SUBDIRS)
$(SUBDIRS):
	$(MAKE) -C $@ $(MAKECMDGOALS)

.PHONY: $(TOPTARGETS) $(SUBDIRS)

