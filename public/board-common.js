// ============================================================
// board-common.js — Shared logic for board.html & bigscreen.html
// ============================================================

const COLOR_PALETTE = [
    'var(--info)', '#a855f7', 'var(--success)', 'var(--warning)', 'var(--danger)',
    '#f1c40f', '#1dd1a1', '#7c3aed', '#ff6b9d', '#54a0ff'
];

// ===================== BoardAPI =====================
const BoardAPI = {
    buildUrl(category) {
        const params = new URLSearchParams();
        const tok = new URLSearchParams(window.location.search).get('token');
        if (tok) params.set('token', tok);
        if (category) params.set('category', category);
        const qs = params.toString();
        return '/api/dashboard/board' + (qs ? '?' + qs : '');
    },
    async fetchData(category) {
        const res = await fetch(this.buildUrl(category));
        if (!res.ok) throw new Error('API ' + res.status);
        const d = await res.json();
        return {
            stats: d.stats || {},
            today: d.today || {},
            orders: d.orders || [],
            overdue_orders: d.overdue_orders || [],
            worker_stats: d.worker_stats || [],
            process_stats: d.process_stats || [],
            recent_reports: d.recent_reports || [],
            update_time: d.update_time || ''
        };
    }
};

// ===================== BoardUtils =====================
const BoardUtils = {
    avColor(name) {
        if (!name) return COLOR_PALETTE[0];
        let hash = 0;
        for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
        return COLOR_PALETTE[Math.abs(hash) % COLOR_PALETTE.length];
    },
    isOverdue(order) {
        if (!order || !order.plan_end) return false;
        const d = new Date();
        const local = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
        return order.plan_end < local;
    },
    fmt(ts) {
        if (!ts) return '';
        const d = new Date(ts);
        return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    },
    procPct(item, maxProc) {
        if (!maxProc || !item || !item.output) return 0;
        return Math.max((item.output / maxProc) * 100, 4);
    },
    tickFull() {
        return new Date().toLocaleString('zh-CN', {
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
        });
    },
    tickTime() {
        return new Date().toLocaleString('zh-CN', {
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
        });
    },
    statusMap() {
        return { pending: '待生产', producing: '生产中', completed: '已完成' };
    }
};
