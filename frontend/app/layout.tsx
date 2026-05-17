import './globals.css'
import { Providers } from './providers'

export const metadata = {
  title: 'JackSparrow — Delta Testnet',
  description: 'AI-Powered Trading Agent for Delta Exchange India Testnet',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}

