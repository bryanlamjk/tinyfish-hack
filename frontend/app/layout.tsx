import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
	title: "TravellingFish",
	description:
		"Concurrent TinyFish search dashboard with live agent streams.",
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="en" suppressHydrationWarning>
			<body suppressHydrationWarning>{children}</body>
		</html>
	);
}
