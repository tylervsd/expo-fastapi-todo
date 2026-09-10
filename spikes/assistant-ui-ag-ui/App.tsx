import '@expo/metro-runtime';
import React, { useMemo, useState } from 'react';
import { Button, Text, TextInput, View } from 'react-native';
import { AssistantRuntimeProvider, ThreadPrimitive } from '@assistant-ui/react-native';
import { useAgUiRuntime } from '@assistant-ui/react-ag-ui';
import { HttpAgent } from '@ag-ui/client';

export default function App() {
  const [answer, setAnswer] = useState('Saturday');
  const [error, setError] = useState('');
  const agent = useMemo(() => new HttpAgent({
    url: 'http://127.0.0.1:8001/agent',
    headers: { Authorization: 'Bearer fixture-only' },
  }), []);
  const runtime = useAgUiRuntime({ agent, onError: e => setError(String(e)) });
  return <AssistantRuntimeProvider runtime={runtime}>
    <ThreadPrimitive.Root style={{ flex: 1, padding: 28, paddingTop: 70, gap: 16 }}>
      <Text style={{ fontSize: 24 }}>assistant-ui + AG-UI spike</Text>
      <Button title="Plan birthday party" onPress={() => runtime.thread.append('Plan birthday party')} />
      <Button title="Test slow stream" onPress={() => runtime.thread.append('slow')} />
      <Button title="Cancel" onPress={() => runtime.thread.cancelRun()} />
      <Text accessibilityRole="alert">{error}</Text>
      <ThreadPrimitive.MessagesFlatList>
        {({ message }) => <View style={{ padding: 12, gap: 12 }}>
          {message.content.map((part, index) => {
            if (part.type === 'text') return <Text key={index}>{part.text}</Text>;
            if (part.type !== 'tool-call') return null;
            if (part.toolName !== 'clarify_plan') return <Text key={index}>Unsupported tool</Text>;
            return <View key={index} style={{ padding: 16, gap: 12, backgroundColor: '#edf2ff' }}>
              <Text>When is the party?</Text>
              {part.result === undefined ? <>
                <TextInput accessibilityLabel="Party date" value={answer} onChangeText={setAnswer} style={{ borderWidth: 1, padding: 10 }} />
                <Button title="Submit answer" onPress={() => runtime.thread.getMessageById(message.id).getMessagePartByToolCallId(part.toolCallId).addToolResult({ answer })} />
              </> : <Text>Answer sent: {JSON.stringify(part.result)}</Text>}
            </View>;
          })}
        </View>}
      </ThreadPrimitive.MessagesFlatList>
    </ThreadPrimitive.Root>
  </AssistantRuntimeProvider>;
}
