import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
	title: "TravellingFish",
	description:
		"AI itinerary planner and concurrent TinyFish search dashboard.",
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
