import "./globals.css";
export const metadata = {
  title: "IntegrationOps · API health & incident monitoring",
  description:
    "Monitor external API health, identify failures, and track recovery.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
