// SettingsPage Component
import { useSettings } from '../../composables/useSettings.js'

export default {
  template: '#settings-page-template',
  setup() {
    return useSettings()
  }
}
