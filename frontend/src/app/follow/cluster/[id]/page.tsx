"use client";

import { use } from "react";
import { FollowFeedPage } from "@/components/FollowFeedPage";

export default function FollowClusterPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <FollowFeedPage kind="cluster" id={id} />;
}
