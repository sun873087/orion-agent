import { useTranslation } from '../../i18n'

export function AboutSection() {
  const { t } = useTranslation()
  return <div className="text-sm text-fg-muted">{t('settings.about.text')}</div>
}
