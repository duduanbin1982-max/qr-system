// Login Component
// Template: #login-template in index-v2.html
import { ref, onMounted } from '../vendor/vue.esm.js'

export default {
  template: '#login-template',
  setup(props, { emit }) {
    const username = ref('')
    const password = ref('')
    const error = ref('')
    const loading = ref(false)
    
    async function handleSubmit() {
      if (!username.value || !password.value) {
        error.value = '请输入用户名和密码'
        return
      }
      loading.value = true
      error.value = ''
      try {
        const { login } = await import('../auth.js')
        await login(username.value, password.value)
        const { navigate } = await import('../router.js')
        navigate('dashboard')
      } catch(e) {
        error.value = e.message || '登录失败'
      } finally {
        loading.value = false
      }
    }
    
    return { username, password, error, loading, handleSubmit }
  }
}
