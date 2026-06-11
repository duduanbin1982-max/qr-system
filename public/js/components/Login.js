// Login Component
// Template: #login-template in index-v2.html
import { ref, onMounted } from '../vendor/vue.esm.js'

export default {
  template: '#login-template',
  setup(props, { emit }) {
    const username = ref('')
    const password = ref('')
    const newPassword = ref('')
    const confirmPassword = ref('')
    const error = ref('')
    const loading = ref(false)
    const showChangePassword = ref(false)
    
    async function handleSubmit() {
      if (!username.value || !password.value) {
        error.value = '请输入用户名和密码'
        return
      }
      loading.value = true
      error.value = ''
      try {
        const { login } = await import('../auth.js')
        const result = await login(username.value, password.value)
        if (result.mustChangePassword) {
          showChangePassword.value = true
          error.value = ''
        } else {
          const { navigate } = await import('../router.js')
          navigate('dashboard')
        }
      } catch(e) {
        error.value = e.message || '登录失败'
      } finally {
        loading.value = false
      }
    }

    async function handleChangePassword() {
      if (!newPassword.value || newPassword.value.length < 8) {
        error.value = '新密码至少需要8位'
        return
      }
      if (newPassword.value !== confirmPassword.value) {
        error.value = '两次输入的密码不一致'
        return
      }
      loading.value = true
      error.value = ''
      try {
        const { changePassword } = await import('../auth.js')
        await changePassword(newPassword.value)
        const { navigate } = await import('../router.js')
        navigate('dashboard')
      } catch(e) {
        error.value = e.message || '修改密码失败'
      } finally {
        loading.value = false
      }
    }
    
    return { username, password, newPassword, confirmPassword, error, loading, showChangePassword, handleSubmit, handleChangePassword }
  }
}