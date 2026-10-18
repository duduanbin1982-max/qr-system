import { useWage } from '@/composables/useWage.js'
import { router } from '@/lib/router.js'

export function useWageWorkspace() {
  const wage = useWage()
  const params = router.params || {}
  if (params.wage_tab === 'priceversions') wage.switchTab('priceversions')
  return {
    ...wage,
    priceIntent: {
      route_version_id: Number(params.route_version_id) || null,
      process_version_id: Number(params.process_version_id) || null,
      create_price: Boolean(params.create_price),
    },
  }
}
