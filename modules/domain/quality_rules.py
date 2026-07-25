"""Default rules shared by quality domain services and schema migrations."""


QUALITY_MANAGEMENT_DEFAULT_RULES = {
    "enabled": True,
    "first_article_gate": "hard",
    "in_process_gate": "soft",
    "final_gate": "hard",
    "shipment_gate": "hard",
    "auto_first_article": True,
    "auto_final_inspection": True,
    "auto_outgoing_inspection": True,
    "in_process_frequency": 20,
    "low_evaluation_creates_task": True,
    "capa_repeat_threshold": 3,
    "gauge_due_warning_days": 30,
}


PROCESS_QUALITY_EVALUATION_DEFAULT_RULES = {
    "enabled": True,
    "required_previous_process": True,
    "low_score_threshold": 60,
    "critical_score_threshold": 40,
    "minimum_samples_for_performance": 3,
    "hide_target_identity": True,
    "auto_open_mobile": True,
    "dimensions": [
        {"key": "processing_quality", "label": "加工质量"},
        {"key": "dimensional_accuracy", "label": "尺寸或精度"},
        {"key": "appearance_quality", "label": "外观质量"},
        {"key": "process_continuity", "label": "工序可接续性"},
        {"key": "cleanliness_protection", "label": "清洁及防护"},
    ],
    "issue_tags": ["尺寸问题", "外观问题", "漏加工", "毛刺锐边", "标识不清", "清洁防护", "返修风险", "其他"],
    "critical_issue_tags": ["致命缺陷", "安全风险", "严重尺寸超差"],
}
