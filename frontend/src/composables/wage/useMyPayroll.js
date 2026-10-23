import { onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useMyPayroll() {
  const now=new Date()

  const month=ref(`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`)

  const lines=ref([])

  const loading=ref(false)

  function money(cents){return `¥${(Number(cents||0)/100).toFixed(2)}`}

  async function load(){loading.value=true;try{const data=await api.domains.wages.getMyPayroll(month.value);lines.value=data.lines||[]}catch(error){showToast(error.message||'本人工资加载失败','error')}finally{loading.value=false}}

  onMounted(load)

  return {
    now,
    month,
    lines,
    loading,
    money,
    load
  }
}
