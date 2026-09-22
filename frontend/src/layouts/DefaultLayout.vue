<script setup lang="ts">
import { RouterView } from 'vue-router'

import AppFooter from '../components/AppFooter.vue'
import AppHeader from '../components/AppHeader.vue'
import AppToast from '../components/AppToast.vue'
</script>

<template>
  <div class="app-shell">
    <AppHeader />
    <main class="layout-container page-main">
      <RouterView />
    </main>
    <AppFooter />
    <AppToast />
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}
</style>
