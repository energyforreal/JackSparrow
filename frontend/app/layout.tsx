import './globals.css'

export const metadata = {
  title: 'JackSparrow Trading Agent',
  description: 'AI-Powered Trading Agent for Delta Exchange India Paper Trading',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}

