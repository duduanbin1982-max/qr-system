import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export function useQualityManagement() {
  const tabs = [
    { key:'overview', label:'质量工作台' }, { key:'tasks', label:'检验任务' }, { key:'records', label:'检验记录' },
    { key:'standards', label:'标准方案' }, { key:'ncr', label:'不合格品' }, { key:'capa', label:'CAPA' },
    { key:'suppliers', label:'质量资源' }, { key:'analytics', label:'统计分析' }, { key:'rules', label:'门禁规则', permission:'quality:standards' },
  ]

  const inspectionTypeOptions = [
    {value:'first_article',label:'首件检验'},{value:'in_process',label:'过程检验'},{value:'final',label:'完工检验'},
    {value:'outgoing',label:'出库检验'},{value:'rework_check',label:'返修复检'},{value:'quality_verification',label:'质量核验'},{value:'manual',label:'手工检验'},
  ]

  const triggerOptions = [
    {value:'first_report',label:'首件报工'},{value:'quantity_interval',label:'数量间隔'},{value:'final_process',label:'最终工序完成'},
    {value:'shipment',label:'创建出库单'},{value:'rework_complete',label:'返修完成'},{value:'low_evaluation',label:'低分工序评价'},{value:'manual',label:'手工创建'},
  ]

  const visibleTabs = computed(() => tabs.filter(tab => !tab.permission || can(tab.permission)))

  const canInspect = computed(() => can('quality:inspect') || can('quality:edit'))

  const canStandards = computed(() => can('quality:standards'))

  const canPlans = computed(() => can('quality:plans'))

  const canDisposition = computed(() => can('quality:disposition'))

  const canReview = computed(() => can('quality:review') || can('quality:edit'))

  const canCapa = computed(() => can('quality:capa'))

  const canSupplier = computed(() => can('quality:supplier'))

  const canCalibration = computed(() => can('quality:calibration'))

  const activeTab = ref(localStorage.getItem('qualityManagementTab') || 'overview')

  const standardMode = ref('standards')

  const keyword = ref('')

  const filterStatus = ref('')

  const dateFrom = ref(new Date(Date.now()-30*86400000).toISOString().slice(0,10))

  const dateTo = ref(new Date().toISOString().slice(0,10))

  const dashboard = ref({})

  const refs = reactive({ orders:[], products:[], routes:[], processes:[], users:[], suppliers:[], materials:[] })

  const tasks = ref([]), records = ref([]), standards = ref([]), plans = ref([]), ncrItems = ref([]), capaItems = ref([])

  const supplierInspections = ref([]), supplierStats = ref([]), gauges = ref([]), analytics = ref({})

  const ruleForm = reactive({})

  const showStandard=ref(false), showPlan=ref(false), showTask=ref(false), showInspection=ref(false), showDisposition=ref(false)

  const showCapa=ref(false), showSupplier=ref(false), showGauge=ref(false), showCalibration=ref(false)

  const showReview=ref(false), showNcr=ref(false), showNcrDetail=ref(false)

  const inspectionTask=ref(null), dispositionRow=ref(null), calibrationGauge=ref(null)

  const reviewRow=ref(null), ncrDetail=ref(null)

  const standardForm=reactive({}), planForm=reactive({}), taskForm=reactive({}), inspectionForm=reactive({measurements:[]})

  const dispositionForm=reactive({}), capaForm=reactive({}), supplierForm=reactive({}), gaugeForm=reactive({}), calibrationForm=reactive({})

  const reviewForm=reactive({status:'approved',note:''})

  const ncrForm=reactive({order_id:null,process_id:null,defect_level:'general',defect_quantity:1,defect_category:'',description:'',responsible_user_id:null,owner_id:null,due_at:''})

  const primaryLabel = computed(() => {
    if (activeTab.value==='tasks' && canInspect.value) return '新增任务'
    if (activeTab.value==='standards' && standardMode.value==='standards' && canStandards.value) return '新增标准'
    if (activeTab.value==='standards' && standardMode.value==='plans' && canPlans.value) return '新增方案'
    if (activeTab.value==='capa' && canCapa.value) return '新增 CAPA'
    if (activeTab.value==='suppliers' && canSupplier.value) return '新增来料检验'
    if (activeTab.value==='gauges' && canCalibration.value) return '新增量具'
    if (activeTab.value==='ncr' && canDisposition.value) return '新增质量异常'
    return ''
  })

  async function loadRefs(){ try{Object.assign(refs,await api.domains.qualityManagement.qualityReferences())}catch(e){showToast(e.message||'基础数据加载失败','error')} }

  async function loadDashboard(){ dashboard.value=await api.domains.qualityManagement.qualityDashboard() }

  async function loadTasks(){ const d=await api.domains.qualityManagement.qualityTasks({keyword:keyword.value,status:filterStatus.value,limit:500});tasks.value=d.items||[] }

  async function loadRecords(){ const d=await api.domains.qualityManagement.managedInspections({keyword:keyword.value,result:filterStatus.value,limit:500});records.value=d.items||[] }

  async function loadStandards(){ const d=await api.domains.qualityManagement.qualityStandards({keyword:keyword.value,limit:500});standards.value=d.items||[] }

  async function loadPlans(){ const d=await api.domains.qualityManagement.qualityPlans({keyword:keyword.value,limit:500});plans.value=d.items||[] }

  async function loadNcr(){ const d=await api.domains.qualityManagement.qualityNcr({keyword:keyword.value,status:filterStatus.value,limit:500});ncrItems.value=d.items||[] }

  async function loadCapa(){ const d=await api.domains.qualityManagement.qualityCapa({keyword:keyword.value,status:filterStatus.value,limit:500});capaItems.value=d.items||[] }

  async function loadSuppliers(){ const d=await api.domains.qualityManagement.supplierInspections({keyword:keyword.value,result:filterStatus.value,limit:500});supplierInspections.value=d.items||[];supplierStats.value=d.supplier_stats||[] }

  async function loadGauges(){ const d=await api.domains.qualityManagement.qualityGauges({keyword:keyword.value,status:filterStatus.value,limit:500});gauges.value=d.items||[] }

  async function loadAnalytics(){ analytics.value=await api.domains.qualityManagement.qualityAnalytics({from:dateFrom.value,to:dateTo.value}) }

  async function loadRules(){ Object.assign(ruleForm,await api.domains.qualityManagement.qualityRules()) }

  async function loadActive(){
    try{
      if(activeTab.value==='overview')await loadDashboard()
      if(activeTab.value==='tasks')await loadTasks()
      if(activeTab.value==='records')await loadRecords()
      if(activeTab.value==='standards'){await loadStandards();await loadPlans()}
      if(activeTab.value==='ncr')await loadNcr()
      if(activeTab.value==='capa')await loadCapa()
      if(activeTab.value==='suppliers')await loadSuppliers()
      if(activeTab.value==='gauges')await loadGauges()
      if(activeTab.value==='analytics')await loadAnalytics()
      if(activeTab.value==='rules')await loadRules()
      if(activeTab.value!=='overview')await loadDashboard()
    }catch(e){showToast(e.message||'质量数据加载失败','error')}
  }

  async function switchTab(key){activeTab.value=key;filterStatus.value='';keyword.value='';localStorage.setItem('qualityManagementTab',key);await loadActive()}

  function openPrimary(){if(activeTab.value==='tasks')openTask();else if(activeTab.value==='standards'&&standardMode.value==='standards')openStandard();else if(activeTab.value==='standards')openPlan();else if(activeTab.value==='capa')openCapa();else if(activeTab.value==='suppliers')openSupplier();else if(activeTab.value==='gauges')openGauge();else if(activeTab.value==='ncr')openNcr()}

  function openReview(row){reviewRow.value=row;Object.assign(reviewForm,{status:'approved',note:''});showReview.value=true}

  async function saveReview(){try{await api.domains.qualityManagement.reviewQualityInspection(reviewRow.value.id,{...reviewForm});showReview.value=false;showToast('检验审核已保存');await loadRecords();await loadDashboard()}catch(e){showToast(e.message||'审核失败','error')}}

  function openNcr(){Object.assign(ncrForm,{order_id:null,process_id:null,defect_level:'general',defect_quantity:1,defect_category:'',description:'',responsible_user_id:null,owner_id:null,due_at:''});showNcr.value=true}

  async function saveNcr(){try{await api.domains.qualityManagement.createQualityNcr({...ncrForm});showNcr.value=false;showToast('质量异常已创建');await loadNcr();await loadDashboard()}catch(e){showToast(e.message||'创建异常失败','error')}}

  async function openNcrDetail(row){try{const result=await api.domains.qualityManagement.qualityNcrDetail(row.id);ncrDetail.value=result.ncr;showNcrDetail.value=true}catch(e){showToast(e.message||'异常详情加载失败','error')}}

  function emptyStandardItem(){return {item_code:'',item_name:'',item_type:'numeric',unit:'',nominal_value:'',lower_limit:'',upper_limit:'',required:true,weight:0,inspection_method:'',acceptance_criteria:''}}

  function openStandard(){Object.assign(standardForm,{id:null,standard_no:'',name:'',product_code:'',route_id:null,process_id:null,inspection_type:'in_process',version:1,status:'active',gate_mode:'soft',sampling_mode:'fixed',sample_value:1,min_score:85,acceptance_rule:'all_required_pass',notes:'',items:[emptyStandardItem()]});showStandard.value=true}

  async function editStandard(row){const d=await api.domains.qualityManagement.qualityStandard(row.id);Object.assign(standardForm,{...d.standard,items:(d.standard.items||[]).map(i=>({...i,required:!!i.required}))});showStandard.value=true}

  function addStandardItem(){standardForm.items.push(emptyStandardItem())}

  async function saveStandard(){try{const payload=JSON.parse(JSON.stringify(standardForm));if(standardForm.id)await api.domains.qualityManagement.updateQualityStandard(standardForm.id,payload);else await api.domains.qualityManagement.createQualityStandard(payload);showStandard.value=false;showToast('质量标准已保存');await loadStandards()}catch(e){showToast(e.message||'保存失败','error')}}

  async function archiveStandard(row){if(!confirm(`确定停用质量标准 ${row.standard_no} 吗？`))return;await api.domains.qualityManagement.archiveQualityStandard(row.id);await loadStandards()}

  function openPlan(){Object.assign(planForm,{id:null,name:'',standard_id:null,product_code:'',route_id:null,process_id:null,trigger_type:'manual',inspection_type:'in_process',gate_mode:'soft',sampling_mode:'fixed',sample_value:1,frequency_qty:0,due_minutes:120,status:'active'});showPlan.value=true}

  function editPlan(row){Object.assign(planForm,{...row,route_id:row.route_id||null,process_id:row.process_id||null,standard_id:row.standard_id||null});showPlan.value=true}

  async function savePlan(){try{const payload={...planForm};if(planForm.id)await api.domains.qualityManagement.updateQualityPlan(planForm.id,payload);else await api.domains.qualityManagement.createQualityPlan(payload);showPlan.value=false;showToast('检验方案已保存');await loadPlans()}catch(e){showToast(e.message||'保存失败','error')}}

  async function archivePlan(row){if(!confirm(`确定停用检验方案 ${row.name} 吗？`))return;await api.domains.qualityManagement.archiveQualityPlan(row.id);await loadPlans()}

  function openTask(){Object.assign(taskForm,{order_id:null,process_id:null,inspection_type:'manual',standard_id:null,serial_no:'',batch_no:'',sample_qty:1,gate_mode:'soft',priority:'normal',assigned_to:null});showTask.value=true}

  async function saveTask(){try{await api.domains.qualityManagement.createQualityTask({...taskForm});showTask.value=false;showToast('检验任务已创建');await loadTasks()}catch(e){showToast(e.message||'创建失败','error')}}

  async function startTask(row){try{await api.domains.qualityManagement.startQualityTask(row.id);await openInspection(row)}catch(e){showToast(e.message||'开始任务失败','error')}}

  async function openInspection(row){try{const d=await api.domains.qualityManagement.qualityTask(row.id);inspectionTask.value=d.task;const measurements=(d.task.standard_items||[]).map(item=>({item_id:item.id,item_code:item.item_code,item_name:item.item_name,item_type:item.item_type,unit:item.unit,weight:item.weight,value:item.item_type==='boolean'?true:item.item_type==='score'?item.weight:'',note:'',nominal:item.nominal_value,lower:item.lower_limit,upper:item.upper_limit,criteria:item.acceptance_criteria}));Object.assign(inspectionForm,{quantity_checked:d.task.sample_qty||1,quantity_failed:0,result:'pass',defect_level:'',defect_category:'',responsible_process_id:d.task.process_id||null,notes:'',measurements});showInspection.value=true}catch(e){showToast(e.message||'任务详情加载失败','error')}}

  async function submitInspection(){try{await api.domains.qualityManagement.inspectQualityTask(inspectionTask.value.id,JSON.parse(JSON.stringify(inspectionForm)));showInspection.value=false;showToast('检验结果已提交');await loadTasks();await loadDashboard()}catch(e){showToast(e.message||'提交失败','error')}}

  function openDisposition(row){dispositionRow.value=row;Object.assign(dispositionForm,{disposition:row.disposition&&row.disposition!=='pending'?row.disposition:'rework',owner_id:row.owner_id||null,responsible_user_id:row.responsible_user_id||null,responsible_process_id:row.responsible_process_id||row.process_id||null,due_at:row.due_at?.slice(0,10)||'',root_cause:row.root_cause||'',corrective_action:row.corrective_action||'',note:''});showDisposition.value=true}

  async function saveDisposition(){try{await api.domains.qualityManagement.disposeQualityNcr(dispositionRow.value.id,{...dispositionForm});showDisposition.value=false;showToast('不合格处置已保存');await loadNcr();await loadDashboard()}catch(e){showToast(e.message||'处置失败','error')}}

  function openCapa(row=null,ncr=null){Object.assign(capaForm,row?{...row}:{id:null,ncr_id:ncr?.id||null,title:ncr?`${ncr.ncr_no} 质量改进`:'',problem_description:ncr?.description||'',root_cause:'',corrective_action:'',preventive_action:'',owner_id:null,due_at:'',status:'open',effectiveness_result:''});showCapa.value=true}

  async function saveCapa(){try{const payload={...capaForm};if(capaForm.id)await api.domains.qualityManagement.updateQualityCapa(capaForm.id,payload);else await api.domains.qualityManagement.createQualityCapa(payload);showCapa.value=false;showToast('CAPA 已保存');if(activeTab.value==='capa')await loadCapa()}catch(e){showToast(e.message||'保存失败','error')}}

  function openSupplier(){Object.assign(supplierForm,{supplier_id:null,material_id:null,batch_no:'',delivery_no:'',quantity_checked:1,quantity_failed:0,result:'pass',score_total:100,defect_level:'',defect_category:'',notes:''});showSupplier.value=true}

  async function saveSupplierInspection(){try{await api.domains.qualityManagement.createSupplierInspection({...supplierForm});showSupplier.value=false;showToast('来料检验已保存');await loadSuppliers();await loadDashboard()}catch(e){showToast(e.message||'保存失败','error')}}

  function openGauge(row=null){Object.assign(gaugeForm,row?{...row}:{id:null,gauge_no:'',name:'',model:'',measurement_range:'',accuracy:'',location:'',calibration_cycle_days:365,status:'active',owner_id:null,remark:''});showGauge.value=true}

  async function saveGauge(){try{const payload={...gaugeForm};if(gaugeForm.id)await api.domains.qualityManagement.updateQualityGauge(gaugeForm.id,payload);else await api.domains.qualityManagement.createQualityGauge(payload);showGauge.value=false;showToast('量具已保存');await loadGauges()}catch(e){showToast(e.message||'保存失败','error')}}

  function openCalibration(row){calibrationGauge.value=row;const today=new Date();const next=new Date(today.getTime()+(row.calibration_cycle_days||365)*86400000);Object.assign(calibrationForm,{calibrated_at:today.toISOString().slice(0,10),next_calibration_at:next.toISOString().slice(0,10),result:'pass',certificate_no:'',organization:'',notes:''});showCalibration.value=true}

  async function saveCalibration(){try{await api.domains.qualityManagement.calibrateQualityGauge(calibrationGauge.value.id,{...calibrationForm});showCalibration.value=false;showToast('校准记录已保存');await loadGauges();await loadDashboard()}catch(e){showToast(e.message||'保存失败','error')}}

  async function saveRules(){try{Object.assign(ruleForm,await api.domains.qualityManagement.saveQualityRules({...ruleForm}));showToast('质量门禁规则已保存')}catch(e){showToast(e.message||'保存失败','error')}}

  function typeLabel(v){return Object.fromEntries(inspectionTypeOptions.map(i=>[i.value,i.label]))[v]||v||'-'}

  function triggerLabel(v){return Object.fromEntries(triggerOptions.map(i=>[i.value,i.label]))[v]||v||'-'}

  function taskStatusLabel(v){return {pending:'待检',in_progress:'检验中',passed:'已通过',failed:'不合格',cancelled:'已取消'}[v]||v}

  function ncrStatusLabel(v){return {open:'待处置',processing:'处理中',pending_reinspection:'待复检',closed:'已关闭',cancelled:'已取消'}[v]||v}

  function capaStatusLabel(v){return {open:'待分析',processing:'执行中',verified:'已验证',closed:'已关闭'}[v]||v}

  function resultLabel(v){return {pass:'合格',rework:'返修',scrap:'报废',return:'退货'}[v]||v||'-'}

  function resultClass(v){return v==='pass'?'badge-success':v==='rework'?'badge-warning':'badge-danger'}

  function statusClass(v){return ['passed','closed','verified'].includes(v)?'badge-success':['pending','open','pending_reinspection'].includes(v)?'badge-warning':['failed','cancelled'].includes(v)?'badge-danger':'badge-info'}

  function defectLevelLabel(v){return {minor:'轻微',general:'一般',severe:'严重',critical:'致命'}[v]||'-'}

  function dispositionLabel(v){return {pending:'待判定',rework:'返修',scrap:'报废',concession:'让步接收',isolate:'隔离',return:'退回'}[v]||v||'-'}

  function gateLabel(v){return {hard:'强拦截',soft:'软提示',off:'关闭'}[v]||v||'-'}

  function gaugeStatusLabel(v){return {active:'在用',suspended:'停用',scrapped:'报废'}[v]||v}

  function sourceLabel(v){return {inspection:'生产检验',supplier_inspection:'来料检验',legacy:'历史抽检'}[v]||v||'-'}

  function scopeLabel(row){return [row.product_code,row.route_name,row.process_name].filter(Boolean).join(' / ')||'全局'}

  function samplingLabel(row){return row.sampling_mode==='full'?'全检':row.sampling_mode==='ratio'?`${row.sample_value}%`:`${row.sample_value} 件`}

  function passRate(checked,failed){return checked?Math.round((checked-failed)*1000/checked)/10:0}

  function supplierPassRate(row){return row.inspection_count?Math.round(row.pass_count*1000/row.inspection_count)/10:0}

  function measurementStandard(m){if(m.item_type==='numeric')return [m.lower!==''?`≥${m.lower}`:'',m.upper!==''?`≤${m.upper}`:'',m.unit].filter(Boolean).join(' ');if(m.item_type==='score')return `满分 ${m.weight}`;return m.criteria||m.nominal||'按标准判定'}

  onMounted(async()=>{if(!visibleTabs.value.some(tab=>tab.key===activeTab.value))activeTab.value='overview';await loadRefs();await loadStandards();await loadActive()})

  return {
    tabs,
    inspectionTypeOptions,
    triggerOptions,
    visibleTabs,
    canInspect,
    canStandards,
    canPlans,
    canDisposition,
    canReview,
    canCapa,
    canSupplier,
    canCalibration,
    activeTab,
    standardMode,
    keyword,
    filterStatus,
    dateFrom,
    dateTo,
    dashboard,
    refs,
    tasks,
    records,
    standards,
    plans,
    ncrItems,
    capaItems,
    supplierInspections,
    supplierStats,
    gauges,
    analytics,
    ruleForm,
    showStandard,
    showPlan,
    showTask,
    showInspection,
    showDisposition,
    showCapa,
    showSupplier,
    showGauge,
    showCalibration,
    showReview,
    showNcr,
    showNcrDetail,
    inspectionTask,
    dispositionRow,
    calibrationGauge,
    reviewRow,
    ncrDetail,
    standardForm,
    planForm,
    taskForm,
    inspectionForm,
    dispositionForm,
    capaForm,
    supplierForm,
    gaugeForm,
    calibrationForm,
    reviewForm,
    ncrForm,
    primaryLabel,
    loadRefs,
    loadDashboard,
    loadTasks,
    loadRecords,
    loadStandards,
    loadPlans,
    loadNcr,
    loadCapa,
    loadSuppliers,
    loadGauges,
    loadAnalytics,
    loadRules,
    loadActive,
    switchTab,
    openPrimary,
    openReview,
    saveReview,
    openNcr,
    saveNcr,
    openNcrDetail,
    emptyStandardItem,
    openStandard,
    editStandard,
    addStandardItem,
    saveStandard,
    archiveStandard,
    openPlan,
    editPlan,
    savePlan,
    archivePlan,
    openTask,
    saveTask,
    startTask,
    openInspection,
    submitInspection,
    openDisposition,
    saveDisposition,
    openCapa,
    saveCapa,
    openSupplier,
    saveSupplierInspection,
    openGauge,
    saveGauge,
    openCalibration,
    saveCalibration,
    saveRules,
    typeLabel,
    triggerLabel,
    taskStatusLabel,
    ncrStatusLabel,
    capaStatusLabel,
    resultLabel,
    resultClass,
    statusClass,
    defectLevelLabel,
    dispositionLabel,
    gateLabel,
    gaugeStatusLabel,
    sourceLabel,
    scopeLabel,
    samplingLabel,
    passRate,
    supplierPassRate,
    measurementStandard
  }
}
