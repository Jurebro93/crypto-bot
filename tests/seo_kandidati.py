"""28.11.: tests of the candidate sections of ui/seoindex (caps, stability, the old weekly growth, the hubs) run with
SEO_CORE_MAX=0, i.e. every candidate is in the sitemap as before the core of about 40 addresses
(tests/test_seo_jezgra_offline.py tests the core itself).

    from tests.seo_kandidati import setUpModule, tearDownModule  # noqa: F401
"""
import os

_OLD = {}


def setUpModule():
    _OLD["v"] = os.environ.get("SEO_CORE_MAX")
    os.environ["SEO_CORE_MAX"] = "0"
    from ui import seoindex
    seoindex.reset()


def tearDownModule():
    if _OLD.get("v") is None:
        os.environ.pop("SEO_CORE_MAX", None)
    else:
        os.environ["SEO_CORE_MAX"] = _OLD["v"]
    from ui import seoindex
    seoindex.reset()
