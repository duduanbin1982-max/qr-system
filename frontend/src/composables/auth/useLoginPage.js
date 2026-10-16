import { ref } from 'vue'
import { auth, login, changePassword } from '@/lib/auth.js'
import { navigate, requestedNavigation } from '@/lib/router.js'
import { canOpenPage, getLandingPage } from '@/lib/permissions.js'

export function useLoginPage() {
  const appVersion = __APP_VERSION__
  const username = ref('')
  const password = ref('')
  const newPassword = ref('')
  const confirmPassword = ref('')
  const error = ref('')
  const loading = ref(false)
  const showChangePassword = ref(false)

  function postLoginPage() {
    const requested = requestedNavigation()
    if (requested.settingsTab) {
      localStorage.setItem('settingsTab', requested.settingsTab)
    }
    return requested.page && canOpenPage(auth.user, requested.page)
      ? requested.page
      : getLandingPage(auth.user)
  }

  async function handleSubmit() {
    if (!username.value || !password.value) {
      error.value = '请输入用户名和密码'
      return
    }
    loading.value = true
    error.value = ''
    try {
      const result = await login(username.value, password.value)
      if (result.mustChangePassword) {
        showChangePassword.value = true
        error.value = ''
      } else {
        navigate(postLoginPage())
      }
    } catch (e) {
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
      await changePassword(newPassword.value)
      navigate(postLoginPage())
    } catch (e) {
      error.value = e.message || '修改密码失败'
    } finally {
      loading.value = false
    }
  }

  return { appVersion, username, password, newPassword, confirmPassword, error, loading, showChangePassword, handleSubmit, handleChangePassword }
}
