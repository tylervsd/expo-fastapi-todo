import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AuthenticatedApi } from "./auth/authenticatedApi";
import { TodoScreen } from "./TodoScreen";
import { TodoWorkflowScreen, workflowQueryKey } from "./todoWorkflows/TodoWorkflowScreen";
import {
  defaultUuidGenerator,
  pendingWriteStore,
  type PendingWriteStore,
  type UuidGenerator,
} from "./todoWorkflows/pendingWorkflowWrite";
import {
  keepLatestWorkflow,
  shareWorkflowListSnapshot,
  StaleWorkflowSessionError,
  type WorkflowListSnapshot,
} from "./todoWorkflows/workflowCache";
import type { TodoWorkflow } from "./todos/todoApi";

type ShellMode = "todos" | "workflow-new" | { workflowId: string };

export function discoveryQueryKey(userId: string) {
  return ["todo-workflows", userId, "active"] as const;
}

function planPrompt(item: TodoWorkflow): { title: string; prompt: string } {
  // Both union members can carry view.type "unsupported" (unknown
  // contract vs unknown template), so narrow on the workflow-level title
  // instead of the view discriminant.
  if (!("title" in item)) {
    return { title: "Unsupported saved plan", prompt: item.workflow_id };
  }
  const view = item.view;
  const prompt =
    view.type === "yes_no"
      ? view.question
      : view.type === "unsupported"
        ? "Unsupported step"
        : view.title;
  return { title: item.title, prompt };
}

export function TodoExperience({
  userId,
  api,
  pendingStore = pendingWriteStore,
  generateRequestId = defaultUuidGenerator,
  sessionEpoch,
  isSessionCurrent,
}: {
  userId: string;
  api: AuthenticatedApi;
  pendingStore?: PendingWriteStore;
  generateRequestId?: UuidGenerator;
  sessionEpoch: number;
  isSessionCurrent: (epoch: number) => boolean;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<ShellMode>("todos");

  const discoveryKey = discoveryQueryKey(userId);
  const discoveryQuery = useQuery({
    queryKey: discoveryKey,
    queryFn: async ({ signal }): Promise<WorkflowListSnapshot> => {
      const captured = sessionEpoch;
      const result = await api.listWorkflows({ signal });
      if (!isSessionCurrent(captured)) {
        const previous = queryClient.getQueryData<WorkflowListSnapshot>(discoveryKey);
        if (previous !== undefined) return previous;
        throw new StaleWorkflowSessionError();
      }
      // Seed per-workflow entries without lowering cached revisions, so a
      // selected plan renders instantly and still refetches authoritatively.
      for (const item of result.items) {
        const key = workflowQueryKey(userId, item.workflow_id);
        queryClient.setQueryData<TodoWorkflow>(key, (old) => {
          if (old === undefined) return item;
          if (old.workflow_id !== item.workflow_id) return old;
          return keepLatestWorkflow(old, item);
        });
      }
      return result;
    },
    structuralSharing: (oldData, incoming) =>
      shareWorkflowListSnapshot(oldData, incoming),
    enabled: mode === "todos",
  });

  if (typeof mode === "object") {
    return (
      <TodoWorkflowScreen
        key={mode.workflowId}
        userId={userId}
        api={api}
        onExit={() => setMode("todos")}
        initialWorkflowId={mode.workflowId}
        pendingStore={pendingStore}
        generateRequestId={generateRequestId}
        sessionEpoch={sessionEpoch}
        isSessionCurrent={isSessionCurrent}
      />
    );
  }
  if (mode === "workflow-new") {
    return (
      <TodoWorkflowScreen
        key="new"
        userId={userId}
        api={api}
        onExit={() => setMode("todos")}
        initialWorkflowId={null}
        pendingStore={pendingStore}
        generateRequestId={generateRequestId}
        sessionEpoch={sessionEpoch}
        isSessionCurrent={isSessionCurrent}
      />
    );
  }

  const discoveryError = discoveryQuery.error;
  const showDiscoveryError =
    discoveryError !== null &&
    !(discoveryError instanceof StaleWorkflowSessionError) &&
    !discoveryQuery.isFetching;
  const items = discoveryQuery.data?.items ?? [];
  const showResumeSection =
    discoveryQuery.isPending || showDiscoveryError || items.length > 0;

  return (
    <View style={styles.shell}>
      <TodoScreen api={api} onPlanTask={() => setMode("workflow-new")} />
      {showResumeSection && (
        <View style={styles.resume}>
          <Text accessibilityRole="header" style={styles.resumeHeading}>
            Resume plans
          </Text>
          {discoveryQuery.isPending && <Text style={styles.status}>Loading saved plans…</Text>}
          {showDiscoveryError && (
            <View style={styles.screen}>
              <Text accessibilityRole="alert" style={styles.error}>
                Could not load saved plans.
              </Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Retry loading saved plans"
                style={styles.refreshButton}
                onPress={() => void discoveryQuery.refetch()}
              >
                <Text style={styles.refreshButtonText}>Retry</Text>
              </Pressable>
            </View>
          )}
          {!discoveryQuery.isPending &&
            !showDiscoveryError &&
            items.map((item) => {
              const { title, prompt } = planPrompt(item);
              return (
                <Pressable
                  key={item.workflow_id}
                  accessibilityRole="button"
                  accessibilityLabel={`${title}, ${prompt}`}
                  style={styles.refreshButton}
                  onPress={() => setMode({ workflowId: item.workflow_id })}
                >
                  <Text style={styles.refreshButtonText}>{title}</Text>
                  <Text style={styles.resumePrompt}>{prompt}</Text>
                </Pressable>
              );
            })}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
  },
  screen: {
    gap: 10,
  },
  resume: {
    gap: 10,
    paddingHorizontal: 24,
    paddingVertical: 12,
  },
  resumeHeading: {
    color: "#172033",
    fontSize: 22,
    fontWeight: "700",
  },
  resumePrompt: {
    color: "#42526b",
    fontSize: 14,
  },
  status: {
    color: "#42526b",
    fontSize: 15,
  },
  error: {
    color: "#b42318",
    fontSize: 15,
  },
  refreshButton: {
    alignItems: "center",
    borderColor: "#aeb9c9",
    borderRadius: 10,
    borderWidth: 1,
    justifyContent: "center",
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  refreshButtonText: {
    color: "#173da0",
    fontSize: 16,
    fontWeight: "700",
  },
});
