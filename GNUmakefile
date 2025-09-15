
TOPTARGETS := all clean
SUBDIRS := cases/DischargeInception/Rod/. cases/ItoKMC/StreamerIntegralCriterion/.

$(TOPTARGETS): $(SUBDIRS)
$(SUBDIRS):
	$(MAKE) -C $@ $(MAKECMDGOALS)

.PHONY: $(TOPTARGETS) $(SUBDIRS)

