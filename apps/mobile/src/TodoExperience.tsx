import { useState } from "react";
import type { AuthenticatedApi } from "./auth/authenticatedApi";
import { TodoScreen } from "./TodoScreen";
import { TodoWorkflowScreen } from "./todoWorkflows/TodoWorkflowScreen";

type ShellMode = "todos" | "workflow";

export function TodoExperience({
  userId,
  api,
}: {
  userId: string;
  api: AuthenticatedApi;
}): React.JSX.Element {
  const [mode, setMode] = useState<ShellMode>("todos");

  if (mode === "workflow") {
    return (
      <TodoWorkflowScreen userId={userId} api={api} onExit={() => setMode("todos")} />
    );
  }
  return <TodoScreen api={api} onPlanTask={() => setMode("workflow")} />;
}
