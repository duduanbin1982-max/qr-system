#!/usr/bin/env python3
"""Validate a backend plus built-static release without data migrations."""

import argparse
import ctypes
import json
import os
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

from scripts import code_only_release, deployment_manifest
from scripts.deployment_manifest import sqlite_evidence
from scripts.deployment_manifest import (
    MANAGED_RELEASE_ROOTS,
    normalize_directory_chain,
    safe_tar_members,
)


STATIC_DIRECTORY_MODE = 0o755
STATIC_FILE_MODE = 0o644


ALLOWED_ROOTS = {"modules", "frontend", "tests", "docs"}
ALLOWED_FRONTEND_PATHS = ("frontend/src/", "frontend/index.html")
# Frontend tests travel with a reviewed source release but are never copied
# into the published static tree. Other frontend support paths remain denied.
ALLOWED_FRONTEND_SUPPORT_PATHS = ("frontend/tests/",)
# PR #157 changed this launcher in the business target. The transition is
# admitted only for this exact production baseline and reviewed target tree.
RELEASE_CONTROL_BASELINE = "276bb8236711fdf42557bb98912c3c98e6faa10b"
RELEASE_CONTROL_TARGET = "c67777bdc47dcf47638d5466137a799abeb21ae8"
PINNED_RELEASE_CONTROL_TRANSITIONS = {
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "632ef4642ff6d8576fe1bd6f7dc75d6f8ac2a1f2"),
        ("100644", "blob", "4c9022c964b2fc9f25ef7ebb1d0e78adc4c13b0f"),
    ),
}
# Reviewed support changes accompanying this production baseline only. These
# entries authorize exact Git objects, not a general scripts/tests exception.
SUPPORT_BASELINE = "c0448bfc945bcfa9c09e94ab1d4bf11f93a3c022"
PINNED_SUPPORT_TRANSITIONS = {
    "frontend/tests/unit/inventory-view-state.spec.js": (
        ("100644", "blob", "6c41cf45757bd91eba126dcc002cc4c4c353f58c"),
        ("100644", "blob", "c5c727c2a5278a6d5540695f05bd184e3e736439"),
    ),
    "scripts/bootstrap_task7_release_execute.py": (
        ("100644", "blob", "7eca491d49bc684528a9199a5b9ce6329f02c792"),
        ("100644", "blob", "9adebbb8beae69699c070d5b196ea420318eac7f"),
    ),
    "scripts/bootstrap_task8_release_control.py": (
        None,
        ("100644", "blob", "d61b9b957ed6d1e88a0ba9afcffb7db3a3cdd877"),
    ),
}
# PR #134 support files accompany this exact business release only. The
# independently reviewed tool update remains outside the production target.
PAYROLL_SUPPORT_BASELINE = "df7a6e398ab82eef02160d1efd143e1676d3db08"
PAYROLL_SUPPORT_TARGET = "a1bdb0a4fa3d6aec1139a8db1e2f72707646f1ef"
PINNED_PAYROLL_SUPPORT_TRANSITIONS = {
    "frontend/tests/e2e/payroll-audit-regressions.spec.js": (
        None,
        ("100644", "blob", "ed6750eb656cfcb1a629a574fdfc5f4cf96f8001"),
    ),
    "frontend/tests/unit/payroll-audit-behavior.spec.js": (
        None,
        ("100644", "blob", "2702ffd5f36046d77f0bcadffb99083f189c9cc4"),
    ),
    "frontend/tests/unit/task2d-wage-layers.spec.js": (
        ("100644", "blob", "cfbac7e5c500dbdd35cbd2492eee14d97a8ea535"),
        ("100644", "blob", "b6feeff88072b824641f51a14bc29678699f27bc"),
    ),
    "scripts/bootstrap_task132_release_control.py": (
        None,
        ("100644", "blob", "4651cd756bd9f162c444e8c918ecc09d209f15f0"),
    ),
}
# PR #136 support changes are approved only for these exact production and
# business merge trees. The tool fix that grants this approval is separate.
ORDERS_SUPPORT_BASELINE = "a1bdb0a4fa3d6aec1139a8db1e2f72707646f1ef"
ORDERS_SUPPORT_TARGET = "971a7a3deb307efe0cae765d71abf833e6bf03aa"
PINNED_ORDERS_SUPPORT_TRANSITIONS = {
    "frontend/tests/e2e/admin-pages.spec.js": (
        ("100644", "blob", "888ee644a26c129d87d5d90ffe29ed50f733a2c4"),
        ("100644", "blob", "8c6fd85b8046c176a38ba0db6ad810b3123f9f92"),
    ),
    "frontend/tests/e2e/helpers.js": (
        ("100644", "blob", "234c7ab405955c81c0679e34a3080788c08f3c9d"),
        ("100644", "blob", "5ed81ed951880c0e3355232359adc9222fcbdafb"),
    ),
    "frontend/tests/unit/order-mode-progress.spec.js": (
        ("100644", "blob", "e4ef8a40666efb461c9527565dc88c706a962494"),
        ("100644", "blob", "a185211584c3634bc735a2a543041c465ca2ef96"),
    ),
    "scripts/e2e_server.py": (
        ("100755", "blob", "bfe2ae31b011a6b9f9e809c1d2aa8acd4383bdde"),
        ("100755", "blob", "f223a157124f5ec41e0a23f5d7a36fb762bfb7fa"),
    ),
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "8303fb9cd6fee5bb658fe57f92a1e0df6f203599"),
        ("100644", "blob", "d0abe1a02d23bee4b9327b0eaaaaaccb8e4f37ce"),
    ),
}
# PR #138 support changes are limited to this exact production-to-merge pair.
# The separate tool update is not part of the customer business target.
CUSTOMER_SUPPORT_BASELINE = "971a7a3deb307efe0cae765d71abf833e6bf03aa"
CUSTOMER_SUPPORT_TARGET = "2a5a014d5e99655ad1e9ecdc9ac0ebc670e15875"
PINNED_CUSTOMER_SUPPORT_TRANSITIONS = {
    "frontend/tests/e2e/customer-management.spec.js": (
        None,
        ("100644", "blob", "d478125c6e610d01db284e75166c916ac4d2abb3"),
    ),
    "frontend/tests/unit/CustomerListRequests.spec.js": (
        None,
        ("100644", "blob", "083f92a6a0a06a20799ddd92d640e09da6ecea5d"),
    ),
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "d0abe1a02d23bee4b9327b0eaaaaaccb8e4f37ce"),
        ("100644", "blob", "347a25db4b7ac0504f2933a612c42ad46e35f5f7"),
    ),
}
# PR #140 material-management support files are approved only for this exact
# production-to-merge pair. The separate release-tool update is not part of
# the business target and must be pinned independently.
MATERIALS_SUPPORT_BASELINE = "2a5a014d5e99655ad1e9ecdc9ac0ebc670e15875"
MATERIALS_SUPPORT_TARGET = "d532973ef8e6b427d8018700182059bb737900c7"
PINNED_MATERIALS_SUPPORT_TRANSITIONS = {
    "frontend/tests/e2e/material-audit-regressions.spec.js": (
        None,
        ("100644", "blob", "bded26987d853a57d9bb35eb62dbed07b4c19e19"),
    ),
    "frontend/tests/unit/material-audit-behavior.spec.js": (
        None,
        ("100644", "blob", "1a2db529ef36691796a71819637b624a64fa25a2"),
    ),
    "frontend/tests/unit/material-options-pagination.spec.js": (
        None,
        ("100644", "blob", "05ebe7fa70fd4f26a8f854258ff7ae6b32a42d29"),
    ),
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "347a25db4b7ac0504f2933a612c42ad46e35f5f7"),
        ("100644", "blob", "01f4fdc4ae6cd25c0abce7afffcaec91268dba4f"),
    ),
}
# PR #142 traceability support files are approved only for this exact
# production-to-merge pair. Test support is not a general frontend exception.
TRACEABILITY_SUPPORT_BASELINE = "d532973ef8e6b427d8018700182059bb737900c7"
TRACEABILITY_SUPPORT_TARGET = "e04c40e445135d173b9b0f98f48b820a389e6c99"
PINNED_TRACEABILITY_SUPPORT_TRANSITIONS = {
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "01f4fdc4ae6cd25c0abce7afffcaec91268dba4f"),
        ("100644", "blob", "5f6e5282816caea1d5b88bf4900fa6094c290699"),
    ),
    "frontend/tests/unit/Task2FApplicationLayers.spec.js": (
        ("100644", "blob", "1e398b2539f79a7cbc5b7b118e5871fcd56d496a"),
        ("100644", "blob", "c0325bc97c69ae796f1e26bffc113ca5872baa9a"),
    ),
    "frontend/tests/unit/TraceOverview.spec.js": (
        None,
        ("100644", "blob", "28efccd14ba19b60fce2fe2ae86fafe1e8cd3160"),
    ),
    "frontend/tests/unit/useTraceSearch.spec.js": (
        ("100644", "blob", "2e5fe5e29ca1066ad7d895a7a14951e45bccf881"),
        ("100644", "blob", "6a09c5b9e5bab4126b8458c995a24bcd21a70a81"),
    ),
}
# PR #160 adds the reviewed wage-price UI workflow and its E2E stability
# adjustment. Permit only this exact production-to-merge transition.
PAYROLL_PRICE_UIUX_BASELINE = "c67777bdc47dcf47638d5466137a799abeb21ae8"
PAYROLL_PRICE_UIUX_TARGET = "f708322d9aeaafa927a6e8952ba1af75ca81e8ac"
PINNED_PAYROLL_PRICE_UIUX_TRANSITIONS = {
    "frontend/src/composables/wage/usePriceVersionWorkspace.js": (
        ("100644", "blob", "a7bfca368d079748d50cbb082ab46c1a7b68ff3b"),
        ("100644", "blob", "3c808b5513490b00fc7581a4cf8aa609fe385287"),
    ),
    "frontend/src/views/wage/PriceVersionTab.vue": (
        ("100644", "blob", "f5c84c57a47440f9d7229a2c994ed161ee694293"),
        ("100644", "blob", "fadd27e0e923f0317f857e3318454b2e145b0cbb"),
    ),
    "frontend/tests/e2e/helpers.js": (
        ("100644", "blob", "5ed81ed951880c0e3355232359adc9222fcbdafb"),
        ("100644", "blob", "7b0ccc4ddd3d5872f52a9f1d1bb43fa844d7cf3d"),
    ),
    "frontend/tests/e2e/wage-price-versions.spec.js": (
        ("100644", "blob", "33ab16a88b4ac0d97ccd116b6a152ca2bf12ebee"),
        ("100644", "blob", "b0ce84f3bd36dce16558fb8f9a08627da2047344"),
    ),
    "frontend/tests/unit/PriceVersionTab.spec.js": (
        ("100644", "blob", "77ceb495baaed93524138f2326d737898684fc8b"),
        ("100644", "blob", "27d5407e83afe49e51868389c0459b98c7f4954b"),
    ),
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "4c9022c964b2fc9f25ef7ebb1d0e78adc4c13b0f"),
        ("100644", "blob", "657af47a0260f85a855d0beca1cfad78eb6aebe8"),
    ),
    "tests/test_backend_frontend_static_release.py": (
        ("100644", "blob", "9518643d40573f633e0c5c4569c896a4cba4e797"),
        ("100644", "blob", "ccfa35dfccba07f8a70179eeb9731ffdc491a450"),
    ),
}
# PR #162 adds the reviewed bulk-approval support file and its release-control
# history transition. Permit only this exact production-to-business-merge pair.
PAYROLL_BULK_APPROVAL_BASELINE = "f708322d9aeaafa927a6e8952ba1af75ca81e8ac"
PAYROLL_BULK_APPROVAL_TARGET = "275a6721f49896069c499c27615d772253809a1b"
PINNED_PAYROLL_BULK_APPROVAL_TRANSITIONS = {
    "frontend/tests/unit/PriceVersionTab.spec.js": (
        ("100644", "blob", "27d5407e83afe49e51868389c0459b98c7f4954b"),
        ("100644", "blob", "a94482c2da24e8225a8a13205d4ce41264ac895e"),
    ),
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "657af47a0260f85a855d0beca1cfad78eb6aebe8"),
        ("100644", "blob", "764f58ce9d0b439158394fc503021a7417e2b461"),
    ),
    "tests/test_backend_frontend_static_release.py": (
        ("100644", "blob", "ccfa35dfccba07f8a70179eeb9731ffdc491a450"),
        ("100644", "blob", "48a1c613ca098f43748ef5a364146fe293be8db1"),
    ),
}
# PR #165 carries the reviewed inventory-threshold release-control history
# transition. Admit only this exact production-to-business-merge pair.
INVENTORY_THRESHOLD_BASELINE = "275a6721f49896069c499c27615d772253809a1b"
INVENTORY_THRESHOLD_TARGET = "ca8703c4f1c3e8a31940c918f497f9fa937defc1"
PINNED_INVENTORY_THRESHOLD_TRANSITIONS = {
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "764f58ce9d0b439158394fc503021a7417e2b461"),
        ("100644", "blob", "adcd69a404cdf4016d5785816a4394423e102723"),
    ),
    "tests/test_backend_frontend_static_release.py": (
        ("100644", "blob", "48a1c613ca098f43748ef5a364146fe293be8db1"),
        ("100644", "blob", "7fb2e5d6c65d73ba16fd0c24b39a27978ee98977"),
    ),
}
# PR #167 adds the reviewed product-code-search frontend regression test.
# Permit only this exact production-to-business-merge transition.
PRODUCT_CODE_SEARCH_BASELINE = "ca8703c4f1c3e8a31940c918f497f9fa937defc1"
PRODUCT_CODE_SEARCH_TARGET = "7c415dc6f3afbd4888bd1e395293a24ac6a356e1"
PINNED_PRODUCT_CODE_SEARCH_TRANSITIONS = {
    "frontend/tests/unit/ProductList.spec.js": (
        ("100644", "blob", "1462da372c13cdd04529d7f14627a4988efc16c8"),
        ("100644", "blob", "bf872d7253213a89cefd17ea1eb166476269a036"),
    ),
    "tests/test_backend_frontend_static_release.py": (
        ("100644", "blob", "7fb2e5d6c65d73ba16fd0c24b39a27978ee98977"),
        ("100644", "blob", "72b18b9a155b76fd8205ea135fbc28ad969b0f87"),
    ),
}
# PR #170 adds the reviewed shipment composable regression test. Permit only
# this exact production-to-business-merge transition.
SHIPMENT_SUPPORT_BASELINE = "7c415dc6f3afbd4888bd1e395293a24ac6a356e1"
SHIPMENT_SUPPORT_TARGET = "bebe066a48f04597d475d6067220f69edbb41d5a"
PINNED_SHIPMENT_SUPPORT_TRANSITIONS = {
    "frontend/tests/unit/shipment-composables.spec.js": (
        ("100644", "blob", "e4e2905bd2388cea6ffee738bec26331e19c189c"),
        ("100644", "blob", "49971aa488f97e772c4b0968e25c0eda0be2392b"),
    ),
    # Keep the release-tool regression contract paired with its business merge.
    "tests/test_backend_frontend_static_release.py": (
        ("100644", "blob", "72b18b9a155b76fd8205ea135fbc28ad969b0f87"),
        ("100644", "blob", "c206125d46415fb3ee0362312597a15dbf9cf313"),
    ),
}
# PR #170 also carries the exact release-control tree transition from the
# production baseline. Pin it separately; do not permit a generic control edit.
PINNED_SHIPMENT_CONTROL_TRANSITIONS = {
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "c242c93d0dd3a3bcef916549dc8e09d817aabfc7"),
        ("100644", "blob", "9c75fd47eedc53be794e1d5dda6b114463f81bbb"),
    ),
}
# PR #173 adds one payroll period-control regression test. Permit only this
# exact production-to-merge transition; frontend tests remain denied by default.
PAYROLL_PERIOD_CONTROL_BASELINE = "bebe066a48f04597d475d6067220f69edbb41d5a"
PAYROLL_PERIOD_CONTROL_TARGET = "2ffa312769411ee97bf915d18e2154a25b4f109b"
PINNED_PAYROLL_PERIOD_CONTROL_TRANSITIONS = {
    "frontend/tests/e2e/helpers.js": (
        ("100644", "blob", "7b0ccc4ddd3d5872f52a9f1d1bb43fa844d7cf3d"),
        ("100644", "blob", "37d0f2d44407ef268772e24869372c91068bebcf"),
    ),
    "frontend/tests/e2e/login-recovery.spec.js": (
        None,
        ("100644", "blob", "f42cc217a82c6ec8a218baf7a568122cd4e5b669"),
    ),
    "frontend/tests/unit/payroll-period-control.spec.js": (
        None,
        ("100644", "blob", "305eba2e360ec75e8c2d201e2acf85487d861b01"),
    ),
    "tests/test_backend_frontend_static_release.py": (
        ("100644", "blob", "c206125d46415fb3ee0362312597a15dbf9cf313"),
        ("100644", "blob", "2a6ce7730035e2c7e34bf81267c3d5b33acd9453"),
    ),
}
PINNED_PAYROLL_PERIOD_CONTROL_CONTROL_TRANSITIONS = {
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "9c75fd47eedc53be794e1d5dda6b114463f81bbb"),
        ("100644", "blob", "5529ae62c37d166b299477c28dfe575ec6068815"),
    ),
}
# PR #176 introduces the V97 payroll-settlement workflow. The migration-aware
# launcher consumes these exact support/control transitions; the ordinary
# backend/static launcher continues to reject migration paths and V96->V97.
PAYROLL_SETTLEMENT_BASELINE = "2ffa312769411ee97bf915d18e2154a25b4f109b"
PAYROLL_SETTLEMENT_TARGET = "c369cf212a2054e14cff0d17b76e5501d26a0b06"
PINNED_PAYROLL_SETTLEMENT_SUPPORT_TRANSITIONS = {
    "frontend/tests/e2e/payroll-settlement.spec.js": (
        None,
        ("100644", "blob", "6b4de82f7e94bc7a74fab3a05ad00fa5999e6143"),
    ),
    "frontend/tests/unit/api-transport-contract.spec.js": (
        ("100644", "blob", "86bd56998d0bac6bce1a80b82e46abfc6386a191"),
        ("100644", "blob", "2ec12a081d5362138166bb866bad587ae5991d53"),
    ),
    "frontend/tests/unit/payroll-settlement.spec.js": (
        None,
        ("100644", "blob", "5107a80e2333ff9b4050a55c8db3443798ad3c0a"),
    ),
    "frontend/tests/unit/wageTabs.spec.js": (
        ("100644", "blob", "0bb211ed5078d9168716fdc2f31a800ba75084e0"),
        ("100644", "blob", "938703f1a423acebea046b41dc78f334c822a344"),
    ),
    "tests/test_backend_frontend_static_release.py": (
        ("100644", "blob", "2a6ce7730035e2c7e34bf81267c3d5b33acd9453"),
        ("100644", "blob", "aadf321dd68e072b9ec82ba8a92fec970fbddfad"),
    ),
}
PINNED_PAYROLL_SETTLEMENT_CONTROL_TRANSITIONS = {
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "5529ae62c37d166b299477c28dfe575ec6068815"),
        ("100644", "blob", "5c3fd55d05db4a0c446a188f7f39fa38e09f2637"),
    ),
}
# PR #167 also changed this release-control script. Admit only the exact
# production-to-business-merge transition alongside the reviewed test pin.
PINNED_PRODUCT_CODE_SEARCH_CONTROL_TRANSITIONS = {
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "adcd69a404cdf4016d5785816a4394423e102723"),
        ("100644", "blob", "c242c93d0dd3a3bcef916549dc8e09d817aabfc7"),
    ),
}
PAYROLL_PRICE_UIUX_STRICT_SUPPORT_PATHS = {
    path for path in PINNED_PAYROLL_PRICE_UIUX_TRANSITIONS
    if path.startswith("frontend/tests/") or path == "scripts/backend_frontend_static_release.py"
}
PROTECTED_EXACT_PATHS = {
    "modules/app.py",
    "modules/app_extensions.py",
    "modules/config.py",
    "modules/db.py",
    "modules/deployment_write_fence.py",
    "modules/migrations.py",
    "modules/migration_catalog.py",
    "modules/migration_planning.py",
    "scripts/deploy.sh",
    "scripts/deploy-code-only.sh",
    "scripts/deployment_manifest.py",
    "scripts/rollback-deployment.sh",
    "scripts/backup-db.sh",
    "package.json",
    "package-lock.json",
    ".nvmrc",
    ".node-version",
    ".npmrc",
    "vite.config.js",
}


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _assert_same_blob(repository, before, target, path):
    before_blob = _git(repository, "rev-parse", f"{before}:{path}")
    target_blob = _git(repository, "rev-parse", f"{target}:{path}")
    if before_blob != target_blob:
        raise RuntimeError(f"release cannot change protected path: {path}")


def _tracked_tree_modes(repository, commit):
    result = subprocess.run(
        ["git", "-C", str(repository), "ls-tree", "-r", "-t", "-z", "--full-tree", commit],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    modes = {}
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0].decode("ascii")
        path = raw_path.decode("utf-8", errors="surrogateescape")
        modes[path] = mode
    return modes


def _tree_entry(repository, commit, path):
    entry = _git(repository, "ls-tree", commit, "--", path)
    if not entry:
        return None
    metadata, actual_path = entry.split("\t", 1)
    if actual_path != path:
        raise RuntimeError(f"unexpected support tree entry: {path}")
    return tuple(metadata.split(" "))


def _validate_support_transition(repository, before, target, path):
    pair = (before, target)
    specifications = (
        (
            "traceability",
            PINNED_TRACEABILITY_SUPPORT_TRANSITIONS,
            TRACEABILITY_SUPPORT_BASELINE,
            TRACEABILITY_SUPPORT_TARGET,
            f"traceability support exception requires the reviewed baseline and target: {path}",
        ),
        (
            "materials",
            PINNED_MATERIALS_SUPPORT_TRANSITIONS,
            MATERIALS_SUPPORT_BASELINE,
            MATERIALS_SUPPORT_TARGET,
            f"materials support exception requires the reviewed baseline and target: {path}",
        ),
        (
            "customer",
            PINNED_CUSTOMER_SUPPORT_TRANSITIONS,
            CUSTOMER_SUPPORT_BASELINE,
            CUSTOMER_SUPPORT_TARGET,
            f"customer support exception requires the reviewed baseline and target: {path}",
        ),
        (
            "payroll",
            PINNED_PAYROLL_SUPPORT_TRANSITIONS,
            PAYROLL_SUPPORT_BASELINE,
            PAYROLL_SUPPORT_TARGET,
            f"payroll support exception requires the reviewed baseline and target: {path}",
        ),
        (
            "payroll period control",
            PINNED_PAYROLL_PERIOD_CONTROL_TRANSITIONS,
            PAYROLL_PERIOD_CONTROL_BASELINE,
            PAYROLL_PERIOD_CONTROL_TARGET,
            f"payroll period control support exception requires the reviewed baseline and target: {path}",
        ),
        (
            "payroll settlement",
            PINNED_PAYROLL_SETTLEMENT_SUPPORT_TRANSITIONS,
            PAYROLL_SETTLEMENT_BASELINE,
            PAYROLL_SETTLEMENT_TARGET,
            f"payroll settlement support exception requires the reviewed baseline and target: {path}",
        ),
        (
            "payroll price UI",
            PINNED_PAYROLL_PRICE_UIUX_TRANSITIONS,
            PAYROLL_PRICE_UIUX_BASELINE,
            PAYROLL_PRICE_UIUX_TARGET,
            f"payroll price UI support exception requires the reviewed baseline and target: {path}",
        ),
        (
            "payroll bulk approval",
            PINNED_PAYROLL_BULK_APPROVAL_TRANSITIONS,
            PAYROLL_BULK_APPROVAL_BASELINE,
            PAYROLL_BULK_APPROVAL_TARGET,
            f"payroll bulk approval support exception requires the reviewed baseline and target: {path}",
        ),
        (
            "inventory threshold",
            PINNED_INVENTORY_THRESHOLD_TRANSITIONS,
            INVENTORY_THRESHOLD_BASELINE,
            INVENTORY_THRESHOLD_TARGET,
            f"inventory threshold support exception requires the reviewed baseline and target: {path}",
        ),
        (
            "product code search",
            PINNED_PRODUCT_CODE_SEARCH_TRANSITIONS,
            PRODUCT_CODE_SEARCH_BASELINE,
            PRODUCT_CODE_SEARCH_TARGET,
            f"product code search support exception requires the reviewed baseline and target: {path}",
        ),
        (
            "shipment",
            PINNED_SHIPMENT_SUPPORT_TRANSITIONS,
            SHIPMENT_SUPPORT_BASELINE,
            SHIPMENT_SUPPORT_TARGET,
            f"shipment support exception requires the reviewed baseline and target: {path}",
        ),
        (
            "orders",
            PINNED_ORDERS_SUPPORT_TRANSITIONS,
            ORDERS_SUPPORT_BASELINE,
            ORDERS_SUPPORT_TARGET,
            f"orders support exception requires the reviewed baseline and target: {path}",
        ),
    )
    candidates = []
    for priority, (_, transitions, baseline, reviewed_target, message) in enumerate(specifications):
        if path not in transitions:
            continue
        if pair == (baseline, reviewed_target):
            expected_before, expected_target = transitions[path]
            break
        score = int(before == baseline) + int(target == reviewed_target)
        candidates.append((score, -priority, message))
    else:
        if candidates:
            _, _, message = max(candidates)
            raise RuntimeError(message)
        if before != SUPPORT_BASELINE:
            raise RuntimeError(f"support exception requires the reviewed baseline: {path}")
        expected_before, expected_target = PINNED_SUPPORT_TRANSITIONS[path]
    if (
        _tree_entry(repository, before, path) != expected_before
        or _tree_entry(repository, target, path) != expected_target
    ):
        raise RuntimeError(f"support exception mode/blob transition mismatch: {path}")


def _validate_release_control_transition(repository, before, target, path):
    if (before, target) != (RELEASE_CONTROL_BASELINE, RELEASE_CONTROL_TARGET):
        raise RuntimeError(
            f"release-control transition requires the reviewed baseline and target: {path}"
        )
    expected_before, expected_target = PINNED_RELEASE_CONTROL_TRANSITIONS[path]
    if (
        _tree_entry(repository, before, path) != expected_before
        or _tree_entry(repository, target, path) != expected_target
    ):
        raise RuntimeError(f"release-control mode/blob transition mismatch: {path}")


def _validate_product_code_search_control_transition(repository, before, target, path):
    if (before, target) != (PRODUCT_CODE_SEARCH_BASELINE, PRODUCT_CODE_SEARCH_TARGET):
        raise RuntimeError(
            f"product code search release-control transition requires the reviewed baseline and target: {path}"
        )
    expected_before, expected_target = PINNED_PRODUCT_CODE_SEARCH_CONTROL_TRANSITIONS[path]
    if (
        _tree_entry(repository, before, path) != expected_before
        or _tree_entry(repository, target, path) != expected_target
    ):
        raise RuntimeError(f"product code search release-control mode/blob transition mismatch: {path}")


def _validate_shipment_control_transition(repository, before, target, path):
    if (before, target) != (SHIPMENT_SUPPORT_BASELINE, SHIPMENT_SUPPORT_TARGET):
        raise RuntimeError(
            f"shipment release-control transition requires the reviewed baseline and target: {path}"
        )
    expected_before, expected_target = PINNED_SHIPMENT_CONTROL_TRANSITIONS[path]
    if (
        _tree_entry(repository, before, path) != expected_before
        or _tree_entry(repository, target, path) != expected_target
    ):
        raise RuntimeError(f"shipment release-control mode/blob transition mismatch: {path}")


def _validate_payroll_period_control_transition(repository, before, target, path):
    if (before, target) != (PAYROLL_PERIOD_CONTROL_BASELINE, PAYROLL_PERIOD_CONTROL_TARGET):
        raise RuntimeError(
            f"payroll period-control release-control transition requires the reviewed baseline and target: {path}"
        )
    expected_before, expected_target = PINNED_PAYROLL_PERIOD_CONTROL_CONTROL_TRANSITIONS[path]
    if (
        _tree_entry(repository, before, path) != expected_before
        or _tree_entry(repository, target, path) != expected_target
    ):
        raise RuntimeError(f"payroll period-control release-control mode/blob transition mismatch: {path}")


def _validate_payroll_settlement_control_transition(repository, before, target, path):
    if (before, target) != (PAYROLL_SETTLEMENT_BASELINE, PAYROLL_SETTLEMENT_TARGET):
        raise RuntimeError(
            f"payroll settlement release-control transition requires the reviewed baseline and target: {path}"
        )
    expected_before, expected_target = PINNED_PAYROLL_SETTLEMENT_CONTROL_TRANSITIONS[path]
    if (
        _tree_entry(repository, before, path) != expected_before
        or _tree_entry(repository, target, path) != expected_target
    ):
        raise RuntimeError(f"payroll settlement release-control mode/blob transition mismatch: {path}")


def _validate_paths(repository, before, target, changed):
    for path in changed:
        normalized = PurePosixPath(path).as_posix()
        parts = PurePosixPath(normalized).parts
        lower = normalized.lower()
        target_path = Path(repository, *parts)
        if (
            not parts
            or normalized.startswith("/")
            or ".." in parts
        ):
            raise RuntimeError(f"release contains a path outside backend/frontend scope: {path}")
        if target_path.is_symlink():
            raise RuntimeError(f"release cannot change a symlinked path: {path}")
        if (
            normalized in PINNED_RELEASE_CONTROL_TRANSITIONS
            and (before, target) == (RELEASE_CONTROL_BASELINE, RELEASE_CONTROL_TARGET)
        ):
            _validate_release_control_transition(repository, before, target, normalized)
            continue
        if (
            normalized in PINNED_PRODUCT_CODE_SEARCH_CONTROL_TRANSITIONS
            and (before, target) == (PRODUCT_CODE_SEARCH_BASELINE, PRODUCT_CODE_SEARCH_TARGET)
        ):
            _validate_product_code_search_control_transition(repository, before, target, normalized)
            continue
        if (
            normalized in PINNED_SHIPMENT_CONTROL_TRANSITIONS
            and (before, target) == (SHIPMENT_SUPPORT_BASELINE, SHIPMENT_SUPPORT_TARGET)
        ):
            _validate_shipment_control_transition(repository, before, target, normalized)
            continue
        if (
            normalized in PINNED_PAYROLL_PERIOD_CONTROL_CONTROL_TRANSITIONS
            and (before, target) == (PAYROLL_PERIOD_CONTROL_BASELINE, PAYROLL_PERIOD_CONTROL_TARGET)
        ):
            _validate_payroll_period_control_transition(repository, before, target, normalized)
            continue
        if (
            normalized in PINNED_PAYROLL_SETTLEMENT_CONTROL_TRANSITIONS
            and (before, target) == (PAYROLL_SETTLEMENT_BASELINE, PAYROLL_SETTLEMENT_TARGET)
        ):
            _validate_payroll_settlement_control_transition(repository, before, target, normalized)
            continue
        if (
            (
                normalized in PINNED_PAYROLL_PRICE_UIUX_TRANSITIONS
                and (
                    (before, target) == (PAYROLL_PRICE_UIUX_BASELINE, PAYROLL_PRICE_UIUX_TARGET)
                    or normalized in PAYROLL_PRICE_UIUX_STRICT_SUPPORT_PATHS
                )
            )
            or normalized in PINNED_SUPPORT_TRANSITIONS
            or normalized in PINNED_PAYROLL_SUPPORT_TRANSITIONS
            or normalized in PINNED_PAYROLL_PERIOD_CONTROL_TRANSITIONS
            or normalized in PINNED_PAYROLL_SETTLEMENT_SUPPORT_TRANSITIONS
            or normalized in PINNED_ORDERS_SUPPORT_TRANSITIONS
            or normalized in PINNED_CUSTOMER_SUPPORT_TRANSITIONS
            or normalized in PINNED_MATERIALS_SUPPORT_TRANSITIONS
            or normalized in PINNED_TRACEABILITY_SUPPORT_TRANSITIONS
            or normalized in PINNED_INVENTORY_THRESHOLD_TRANSITIONS
            or normalized in PINNED_PRODUCT_CODE_SEARCH_TRANSITIONS
            or normalized in PINNED_SHIPMENT_SUPPORT_TRANSITIONS
        ):
            _validate_support_transition(repository, before, target, normalized)
            continue
        if parts[0] not in ALLOWED_ROOTS:
            raise RuntimeError(f"release contains a path outside backend/frontend scope: {path}")
        if parts[0] == "modules" and "migration" in lower:
            raise RuntimeError(f"release cannot change migration logic: {path}")
        if normalized in PROTECTED_EXACT_PATHS:
            raise RuntimeError(f"release cannot change protected path: {path}")
        if parts[0] == "frontend" and not any(
            normalized == prefix or normalized.startswith(prefix)
            for prefix in ALLOWED_FRONTEND_PATHS
        ):
            raise RuntimeError(f"frontend release permits source files only: {path}")
        if any(token in lower for token in ("/attachments/", "production.db", "public/static", "dist/")):
            raise RuntimeError(f"release cannot change protected runtime data/assets: {path}")
        if parts[0] == "modules" and code_only_release._path_is_forbidden(normalized):
            raise RuntimeError(f"release contains a forbidden backend path: {path}")
        if parts[0] in {"tests", "docs"}:
            continue
        if parts[0] == "modules":
            continue
        if not any(normalized == prefix or normalized.startswith(prefix) for prefix in ALLOWED_FRONTEND_PATHS):
            raise RuntimeError(f"release path is not deployable code or static source: {path}")

    tree_modes = (
        _tracked_tree_modes(repository, before),
        _tracked_tree_modes(repository, target),
    )
    for path in changed:
        parts = PurePosixPath(path).parts
        prefixes = ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]
        if any(
            modes.get(prefix) in {"120000", "160000"}
            for modes in tree_modes
            for prefix in prefixes
        ):
            raise RuntimeError(f"release cannot change a symlink or submodule path: {path}")


def validate_release(
    tool_root,
    project_root,
    database,
    before_commit,
    target_commit,
    *,
    require_target_object=True,
):
    tool_root = Path(tool_root).resolve(strict=True)
    project_root = Path(project_root).resolve(strict=True)
    if (
        tool_root == project_root
        or tool_root in project_root.parents
        or project_root in tool_root.parents
    ):
        raise RuntimeError("production and target worktrees must be separate and non-nested")
    database_input = Path(database)
    if database_input.is_symlink():
        raise RuntimeError("production database path cannot be a symlink")
    database = database_input.resolve(strict=True)
    try:
        database.relative_to(project_root / "data")
    except ValueError as error:
        raise RuntimeError("production database must remain under project-root/data/") from error

    code_only_release._validate_sha(before_commit, "expected before commit")
    code_only_release._validate_sha(target_commit, "target commit")
    if before_commit == target_commit:
        raise RuntimeError("target commit must differ from the current production commit")
    if _git(tool_root, "rev-parse", "--verify", "HEAD") != target_commit:
        raise RuntimeError("release tool worktree HEAD must equal the target commit")
    code_only_release._assert_clean_except_data(tool_root, allow_data=False)
    code_only_release._assert_clean_except_data(project_root, allow_data=True)
    if _git(project_root, "rev-parse", "--verify", "HEAD") != before_commit:
        raise RuntimeError("production checkout HEAD does not match the confirmed before commit")
    marker = project_root / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("production deployed-commit marker is missing or unsafe")
    if marker.read_text(encoding="ascii").strip().lower() != before_commit:
        raise RuntimeError("production deployed-commit marker does not match the confirmed before commit")
    if require_target_object:
        _git(project_root, "cat-file", "-e", f"{target_commit}^{{commit}}")

    ancestry = subprocess.run(
        ["git", "-C", str(tool_root), "merge-base", "--is-ancestor", before_commit, target_commit],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if ancestry.returncode:
        raise RuntimeError(
            "target commit is not provably based on the confirmed production commit"
        )

    changed = code_only_release._changed_paths(tool_root, before_commit, target_commit)
    if not changed:
        raise RuntimeError("target commit contains no changes from production baseline")
    if not any(
        path.startswith("modules/")
        or any(path == prefix or path.startswith(prefix) for prefix in ALLOWED_FRONTEND_PATHS)
        for path in changed
    ):
        raise RuntimeError("target commit has no backend or frontend source changes to publish")
    tracked_data = {
        "before": code_only_release._tracked_data_paths(tool_root, before_commit),
        "target": code_only_release._tracked_data_paths(tool_root, target_commit),
    }
    if any(tracked_data.values()):
        raise RuntimeError("backend/static release refuses commits that track production data/")
    _validate_paths(tool_root, before_commit, target_commit, changed)
    code_only_release._assert_release_controls_unchanged(tool_root, before_commit, target_commit)
    code_only_release._assert_runtime_fence_unchanged(tool_root, before_commit, target_commit)

    database_evidence = sqlite_evidence(database)
    target_schema = code_only_release._target_schema_version(tool_root)
    if target_schema != database_evidence["user_version"]:
        raise RuntimeError(
            f"schema mismatch: target expects V{target_schema}, production is V{database_evidence['user_version']}"
        )
    package = json.loads((tool_root / "package.json").read_text(encoding="utf-8"))
    toolchain = {
        "node": package["engines"]["node"],
        "npm": package["engines"]["npm"],
    }
    for path in ("package.json", "package-lock.json", ".nvmrc", ".node-version", ".npmrc", "vite.config.js"):
        _assert_same_blob(tool_root, before_commit, target_commit, path)
    return {
        "scope": "backend_frontend_static",
        "operations": {
            "database_migration": False,
            "attachment_migration": False,
            "frontend_publish": True,
        },
        "before_commit": before_commit,
        "target_commit": target_commit,
        "changed_paths": changed,
        "database": database_evidence,
        "target_schema_version": target_schema,
        "tracked_data": tracked_data,
        "toolchain_required": toolchain,
        "production_worktree": "clean_except_untracked_data",
    }


def verify_baseline_checkout(project_root, before_commit):
    """Reject a partial/dirty checkout even when Git HEAD did not move."""
    project_root = Path(project_root).resolve(strict=True)
    if _git(project_root, "rev-parse", "HEAD") != before_commit:
        raise RuntimeError("abort checkout HEAD does not match the baseline")
    marker = project_root / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("abort deployed-commit marker is missing or unsafe")
    if marker.read_text(encoding="ascii").strip() != before_commit:
        raise RuntimeError("abort deployed-commit marker does not match the baseline")
    code_only_release._assert_clean_except_data(project_root, allow_data=True)
    return {"baseline_commit": before_commit, "worktree": "clean_except_untracked_data"}


def extract_target_static(archive_path, destination):
    destination = Path(destination)
    if ".." in destination.parts:
        raise RuntimeError("static staging destination cannot contain parent traversal")
    if destination.parent.name != "public" or not destination.parent.is_dir():
        raise RuntimeError("static staging destination must be under public")
    parent = destination.absolute().parent
    cursor = parent
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise RuntimeError(f"static staging path cannot traverse a symlink: {cursor}")
        cursor = cursor.parent
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("static staging destination already exists or is unsafe")
    destination.mkdir(mode=STATIC_DIRECTORY_MODE, parents=False)
    destination.chmod(STATIC_DIRECTORY_MODE)
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = safe_tar_members(archive, MANAGED_RELEASE_ROOTS)
            for member in members:
                path = PurePosixPath(member.name)
                relative = Path(*path.parts[2:])
                if path.parts[:2] != ("public", "static"):
                    raise RuntimeError("static archive path is outside public/static")
                target = destination / relative
                if member.isdir():
                    target.mkdir(
                        mode=STATIC_DIRECTORY_MODE,
                        parents=True,
                        exist_ok=True,
                    )
                    normalize_directory_chain(
                        target,
                        destination.parent,
                        STATIC_DIRECTORY_MODE,
                    )
                    continue
                target.parent.mkdir(
                    mode=STATIC_DIRECTORY_MODE,
                    parents=True,
                    exist_ok=True,
                )
                normalize_directory_chain(
                    target.parent,
                    destination.parent,
                    STATIC_DIRECTORY_MODE,
                )
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError(f"static archive entry cannot be read: {member.name}")
                with source, target.open("xb") as output:
                    output.write(source.read())
                target.chmod(STATIC_FILE_MODE)
        if not (destination / "index.html").is_file():
            raise RuntimeError("built static release is missing index.html")
        return str(destination)
    except BaseException:
        import shutil

        shutil.rmtree(destination, ignore_errors=True)
        raise


def exchange_directories(left, right):
    left_input = Path(left).absolute()
    right_input = Path(right).absolute()
    if ".." in left_input.parts or ".." in right_input.parts:
        raise RuntimeError("atomic static exchange refuses parent traversal")
    for path in (*left_input.parents, left_input, *right_input.parents, right_input):
        if path.is_symlink():
            raise RuntimeError("atomic static exchange refuses symlink paths")
    left = left_input.resolve(strict=True)
    right = right_input.resolve(strict=True)
    if left.parent != right.parent or not left.is_dir() or not right.is_dir():
        raise RuntimeError("atomic static exchange requires sibling directories")
    if left.is_symlink() or right.is_symlink():
        raise RuntimeError("atomic static exchange refuses symlinks")
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise RuntimeError("atomic static exchange is unsupported by this Linux runtime")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(-100, os.fsencode(left), -100, os.fsencode(right), 2)
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return {"active": str(left), "previous": str(right)}


def create_static_archive(source_directory, archive_path):
    source_input = Path(source_directory).absolute()
    output = Path(archive_path).absolute()
    if ".." in source_input.parts or ".." in output.parts:
        raise RuntimeError("static archive paths cannot contain parent traversal")
    for path in (*source_input.parents, source_input):
        if path.is_symlink():
            raise RuntimeError(f"static build path cannot traverse a symlink: {path}")
    source = source_input.resolve(strict=True)
    for path in (*output.parents, output):
        if path.is_symlink():
            raise RuntimeError(f"static archive path cannot traverse a symlink: {path}")
    if output.exists():
        raise RuntimeError(f"static archive destination already exists: {output}")
    if not source.is_dir():
        raise RuntimeError("static build output is missing or unsafe")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for item in sorted(source.rglob("*")):
            if item.is_symlink():
                raise RuntimeError(f"static build contains a symlink: {item}")
            if not item.is_file():
                continue
            relative = item.relative_to(source).as_posix()
            member = tarfile.TarInfo(f"public/static/{relative}")
            member.size = item.stat().st_size
            member.mode = STATIC_FILE_MODE
            member.mtime = int(item.stat().st_mtime)
            with item.open("rb") as content:
                archive.addfile(member, content)
    with tarfile.open(output, "r:gz") as archive:
        safe_tar_members(archive, MANAGED_RELEASE_ROOTS)
    with tarfile.open(output, "r:gz") as archive:
        if not any(
            item.isfile() and item.name == "public/static/index.html"
            for item in archive.getmembers()
        ):
            raise RuntimeError("static archive is missing public/static/index.html")
    return {"path": str(output), "sha256": code_only_release_sha256(output)}


def code_only_release_sha256(path):
    import hashlib

    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def static_directory_inventory(directory):
    root_input = Path(directory).absolute()
    if ".." in root_input.parts:
        raise RuntimeError("static backup path cannot contain parent traversal")
    for path in (*root_input.parents, root_input):
        if path.is_symlink():
            raise RuntimeError(f"static backup path cannot traverse a symlink: {path}")
    root = root_input.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError("static backup directory is missing or unsafe")
    files = []
    total_bytes = 0
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise RuntimeError(f"static backup cannot contain a symlink: {item}")
        if item.is_dir():
            continue
        if not item.is_file():
            raise RuntimeError(f"static backup contains an unsupported entry: {item}")
        size = item.stat().st_size
        files.append(
            {
                "path": f"public/static/{item.relative_to(root).as_posix()}",
                "size_bytes": size,
                "sha256": code_only_release_sha256(item),
            }
        )
        total_bytes += size
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "manifest_sha256": deployment_manifest.canonical_digest(files),
        "files": files,
    }


def verify_static_backup(directory, archive_path):
    expected = deployment_manifest.archive_inventory(
        archive_path, MANAGED_RELEASE_ROOTS
    )
    observed = static_directory_inventory(directory)
    if observed != expected:
        raise RuntimeError(
            "swapped-out static directory differs from its verified backup archive"
        )
    return observed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--tool-root", required=True)
    preflight.add_argument("--project-root", required=True)
    preflight.add_argument("--database", required=True)
    preflight.add_argument("--before-commit", required=True)
    preflight.add_argument("--target-commit", required=True)
    preflight.add_argument("--check-only", action="store_true")
    baseline = commands.add_parser("verify-baseline-checkout")
    baseline.add_argument("--project-root", required=True)
    baseline.add_argument("--before-commit", required=True)
    extract = commands.add_parser("extract-static")
    extract.add_argument("--archive", required=True)
    extract.add_argument("--destination", required=True)
    exchange = commands.add_parser("exchange-static")
    exchange.add_argument("--active", required=True)
    exchange.add_argument("--staged", required=True)
    archive = commands.add_parser("archive-static")
    archive.add_argument("--source", required=True)
    archive.add_argument("--archive", required=True)
    verify_backup = commands.add_parser("verify-static-backup")
    verify_backup.add_argument("--directory", required=True)
    verify_backup.add_argument("--archive", required=True)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        result = validate_release(
            args.tool_root,
            args.project_root,
            args.database,
            args.before_commit,
            args.target_commit,
            require_target_object=not args.check_only,
        )
    elif args.command == "verify-baseline-checkout":
        result = verify_baseline_checkout(args.project_root, args.before_commit)
    elif args.command == "extract-static":
        result = extract_target_static(args.archive, args.destination)
    elif args.command == "exchange-static":
        result = exchange_directories(args.active, args.staged)
    elif args.command == "verify-static-backup":
        result = verify_static_backup(args.directory, args.archive)
    else:
        result = create_static_archive(args.source, args.archive)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
