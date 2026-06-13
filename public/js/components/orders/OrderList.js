// OrderList Component
import { useOrder } from '../../composables/useOrder.js'

export default {
  template: '#order-list-template',
  setup() {
    return useOrder()
  }
}
