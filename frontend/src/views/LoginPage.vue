<!-- LoginPage.vue -->
<template>
<!-- 扫码报工生产管理系统 — 登录页 -->
<div class="login-wrapper">
  <div class="login-bg"></div>
  <div class="login-container">
    <div class="login-card">
      <!-- 改密表单 -->
      <template v-if="showChangePassword">
        <div class="login-brand">
          <div class="login-logo">🔐</div>
          <h1 class="login-title">首次登录 · 修改密码</h1>
          <p class="login-subtitle">为保障账户安全，请设置新密码</p>
        </div>
        <div class="login-form">
          <div class="login-field">
            <label class="login-label">新密码</label>
            <input class="login-input" v-model="newPassword" type="password"
              placeholder="至少8位字符" @keyup.enter="handleChangePassword" autofocus>
          </div>
          <div class="login-field">
            <label class="login-label">确认密码</label>
            <input class="login-input" v-model="confirmPassword" type="password"
              placeholder="再次输入新密码" @keyup.enter="handleChangePassword">
          </div>
          <div v-if="error" class="login-error">{{ error }}</div>
          <button class="login-btn" @click="handleChangePassword" :disabled="loading">
            <span v-if="!loading">确认修改</span>
            <span v-else class="login-btn-loading">提交中<span class="login-dots">...</span></span>
          </button>
        </div>
      </template>
      <!-- 登录表单 -->
      <template v-else>
      <div class="login-brand">
        <div class="login-logo">🏭</div>
        <h1 class="login-title">生产管理系统</h1>
        <p class="login-subtitle">扫码报工 · 智能制造</p>
      </div>
      <div class="login-form">
        <div class="login-field">
          <input class="login-input" v-model="username" placeholder="请输入用户名" 
            @keyup.enter="handleSubmit" autofocus autocomplete="username">
        </div>
        <div class="login-field">
          <input class="login-input" v-model="password" type="password" 
            placeholder="请输入密码" @keyup.enter="handleSubmit" autocomplete="current-password">
        </div>
        <div v-if="error" class="login-error">{{ error }}</div>
        <button class="login-btn" @click="handleSubmit" :disabled="loading">
          <span v-if="!loading">登 录</span>
          <span v-else class="login-btn-loading">登录中<span class="login-dots">...</span></span>
        </button>
      </div>
      </template>
      <div class="login-footer">
        <span>v2.0 · Hanyun</span>
      </div>
    </div>
  </div>
</div>
</template>

<script>
import { ref } from 'vue'
import { auth, login, changePassword } from '@/lib/auth.js'
import { navigate } from '@/lib/router.js'
import { getLandingPage } from '@/lib/permissions.js'
import { loadPageAccessCatalog } from '@/composables/usePageAccess.js'

export default {
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
        const result = await login(username.value, password.value)
        if (result.mustChangePassword) {
          showChangePassword.value = true
          error.value = ''
        } else {
          await loadPageAccessCatalog(true)
          navigate(getLandingPage(auth.user))
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
        await changePassword(newPassword.value)
        await loadPageAccessCatalog(true)
        navigate(getLandingPage(auth.user))
      } catch(e) {
        error.value = e.message || '修改密码失败'
      } finally {
        loading.value = false
      }
    }
    
    return { username, password, newPassword, confirmPassword, error, loading, showChangePassword, handleSubmit, handleChangePassword }
  }
}
</script>
