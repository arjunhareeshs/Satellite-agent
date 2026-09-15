import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'TRINETRA — Sovereign Satellite Intelligence Retrieval',
  description: 'Semantic Retrieval and Multi-Temporal Change Analysis of Satellite Imagery | SIH26227 Ministry of Defence',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-command-bg text-slate-100 min-h-screen antialiased selection:bg-cyan-500/30 selection:text-cyan-200">
        {children}
      </body>
    </html>
  );
}
