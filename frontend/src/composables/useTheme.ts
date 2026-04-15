import { ref, watch } from 'vue'

type Theme = 'light' | 'dark'

const STORAGE_KEY = 'gbase-theme'
const theme = ref<Theme>('light')

export function useTheme() {
  function apply(t: Theme) {
    theme.value = t
    document.documentElement.setAttribute('data-theme', t)
    localStorage.setItem(STORAGE_KEY, t)
  }

  function init() {
    const saved = localStorage.getItem(STORAGE_KEY) as Theme | null
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    apply(saved || (prefersDark ? 'dark' : 'light'))

    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      if (!localStorage.getItem(STORAGE_KEY)) {
        apply(e.matches ? 'dark' : 'light')
      }
    })
  }

  function toggle() {
    apply(theme.value === 'light' ? 'dark' : 'light')
  }

  return { theme, init, toggle, apply }
}
