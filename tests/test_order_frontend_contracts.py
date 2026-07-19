from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_order_archive_frontend_contract():
    order_list = (PROJECT_ROOT / "frontend/src/views/OrderList.vue").read_text(encoding="utf-8")
    use_order = (PROJECT_ROOT / "frontend/src/composables/useOrder.js").read_text(encoding="utf-8")
    orders_api = (PROJECT_ROOT / "frontend/src/lib/api/orders.js").read_text(encoding="utf-8")

    assert 'v-model="archiveFilter"' in order_list
    assert 'value="active">未完成订单' in order_list
    assert 'value="completed">已完成订单' in order_list
    assert 'value="all">全部订单' in order_list
    assert 'v-if="!isCompletedOrder(o)" class="o-abtn o-edit"' in order_list
    assert '@click="reopenOrder(o)"' in order_list
    assert "已归档只读" in order_list

    assert "const archiveFilter = ref('active')" in use_order
    assert "archive: archiveFilter.value" in use_order
    assert "function isCompletedOrder" in use_order
    assert "function reopenOrder" in use_order
    assert "completedReadonlyToast" in use_order

    assert "reopenOrder:" in orders_api
    assert "'/reopen'" in orders_api
