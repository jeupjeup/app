/** 플랫폼 로고의 간결한 SVG 표현. 외부 이미지 서버에 의존하지 않습니다. */
type Platform = 'instagram' | 'youtube' | 'naver' | 'arxiv' | 'web' | 'text';
type Props = { platform: Platform; size?: number; className?: string };

export function PlatformLogo({ platform, size = 24, className = '' }: Props) {
  const label = { instagram:'Instagram', youtube:'YouTube', naver:'NAVER', arxiv:'arXiv', web:'웹페이지', text:'텍스트' }[platform];
  if (platform === 'instagram') return <svg className={className} width={size} height={size} viewBox="0 0 32 32" role="img" aria-label={label}>
    <defs><linearGradient id="upload-instagram" x1="0" y1="1" x2="1" y2="0"><stop stopColor="#FFD776"/><stop offset=".25" stopColor="#F58529"/><stop offset=".5" stopColor="#DD2A7B"/><stop offset=".75" stopColor="#8134AF"/><stop offset="1" stopColor="#515BD4"/></linearGradient></defs>
    <rect width="32" height="32" rx="9" fill="url(#upload-instagram)"/><rect x="7.5" y="7.5" width="17" height="17" rx="5.6" fill="none" stroke="white" strokeWidth="2.5"/><circle cx="16" cy="16" r="4.4" fill="none" stroke="white" strokeWidth="2.5"/><circle cx="22.1" cy="10" r="1.5" fill="white"/>
  </svg>;
  if (platform === 'youtube') return <svg className={className} width={size} height={size} viewBox="0 0 32 32" role="img" aria-label={label}>
    <rect x="1" y="6" width="30" height="20" rx="6.8" fill="#FF0033"/><path d="m13.2 11.3 9.1 4.7-9.1 4.7Z" fill="white"/>
  </svg>;
  if (platform === 'naver') return <svg className={className} width={size} height={size} viewBox="0 0 32 32" role="img" aria-label={label}>
    <rect width="32" height="32" rx="7" fill="#03C75A"/><path d="M7.5 7.6h5.25l6.6 9.2V7.6h5.1v16.8h-5.15l-6.65-9.18v9.18H7.5Z" fill="white"/>
  </svg>;
  if (platform === 'arxiv') return <svg className={className} width={size} height={size} viewBox="0 0 32 32" role="img" aria-label={label}>
    <rect width="32" height="32" rx="7" fill="#F8EDED"/><path d="M7 10h5l4 6.2 4-6.2h5l-6.5 9.1 5.3 7h-5.2l-2.6-3.8-2.6 3.8H8.2l5.3-7Z" fill="#AD333A"/><circle cx="16" cy="6.4" r="2.2" fill="#AD333A"/>
  </svg>;
  if (platform === 'text') return <svg className={className} width={size} height={size} viewBox="0 0 32 32" role="img" aria-label={label}>
    <rect width="32" height="32" rx="8" fill="#F6E9D9"/><rect x="9" y="7" width="14" height="18" rx="2" fill="#fff" stroke="#B57B48" strokeWidth="1.5"/><path d="M12 13h8M12 17h8M12 21h5" stroke="#B57B48" strokeWidth="1.4" strokeLinecap="round"/>
  </svg>;
  return <svg className={className} width={size} height={size} viewBox="0 0 32 32" role="img" aria-label={label}>
    <rect width="32" height="32" rx="8" fill="#E9F1E9"/><circle cx="16" cy="16" r="9" fill="none" stroke="#6E9675" strokeWidth="1.8"/><path d="M7.5 16h17M16 7c4 3 4 15 0 18M16 7c-4 3-4 15 0 18" stroke="#6E9675" strokeWidth="1.4" fill="none"/>
  </svg>;
}
