// BoardPage Component — 生产进度看板（Composable 拆分）
import { useBoard } from '../../composables/useBoard.js'

export default {
  template: '#board-page-template',
  setup() {
    return useBoard()
  }
}