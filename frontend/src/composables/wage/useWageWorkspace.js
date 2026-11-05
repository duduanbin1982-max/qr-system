import { useWage } from '@/composables/useWage.js'
import { router } from '@/lib/router.js'

export function useWageWorkspace() {
  const wage = useWage()
  const params = router.params || {}
  // URL navigation wins over persisted state, while switchTab enforces visibility.
  if (params.wage_tab) wage.switchTab(params.wage_tab)
  return {
    ...wage,
    priceIntent: {
      route_version_id: Number(params.route_version_id) || null,
      process_version_id: Number(params.process_version_id) || null,
      create_price: Boolean(params.create_price),
    },
  }
}
