"""A redeployed earlier release becomes current again; readiness and the deploy gate then judge it, not the newer one."""

import time

from assureops_api import services as svc
from assureops_domain.db import tenant_session
from assureops_domain.models import Release
from tests.conftest import add_release


def test_the_most_recently_collected_identity_is_current(workspace):
    r1 = add_release(workspace, "R1")
    time.sleep(0.01)
    r2 = add_release(workspace, "R2", {"policy:permission": "fp-new"})
    with tenant_session(workspace) as s:
        assert svc.latest_release(s, f"{workspace}-app").id == r2.id
        s.get(Release, r2.id).last_collected_at = time.time()
    time.sleep(0.01)
    with tenant_session(workspace) as s:  # the customer rolls back: R1 is collected again (same identity, no new row)
        s.get(Release, r1.id).last_collected_at = time.time()
    with tenant_session(workspace) as s:
        assert svc.latest_release(s, f"{workspace}-app").id == r1.id
