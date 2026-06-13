// ProductList Component
import { useProduct } from '../../composables/useProduct.js?v=5'

export default {
  template: '#product-list-template',
  setup() {
    return useProduct()
  }
}
