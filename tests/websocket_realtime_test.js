/**
 * WebSocket Realtime Data Test Script
 * 
 * Tests that realtime data is being sent to the frontend and that
 * messages are fresh (recent timestamps).
 * 
 * Usage:
 *   node tests/websocket_realtime_test.js
 * 
 * Requires: npm install ws
 */

const WebSocket = require('ws');

const WS_URL = process.env.WS_URL || 'ws://localhost:8000/ws';
const TEST_DURATION_MS = 60000; // Test for 60 seconds
const FRESHNESS_THRESHOLD_MS = 5000; // Messages should be within 5 seconds to be considered fresh

const results = new Map();
const messageTimestamps = new Map();

// Expected message types based on our implementation
const expectedMessageTypes = [
  'agent_state',
  'signal_update',
  'reasoning_chain_update',
  'model_prediction_update',
  'market_tick',
  'trade_executed',
  'portfolio_update',
  'health_update',
  'time_sync'
];

// Initialize results for all expected message types
expectedMessageTypes.forEach(type => {
  results.set(type, {
    messageType: type,
    received: false,
    messageCount: 0,
    freshnessScore: 0,
    errors: []
  });
  messageTimestamps.set(type, []);
});

let ws = null;
let isRunning = true;

function calculateFreshnessScore(ages) {
  if (ages.length === 0) return 0;
  
  // Filter messages that are within freshness threshold
  const recentAges = ages.filter(age => age <= FRESHNESS_THRESHOLD_MS);
  
  // Score based on percentage of recent messages
  const recentPercentage = (recentAges.length / ages.length) * 100;
  
  // Also consider average latency (lower is better)
  const avgLatency = ages.reduce((sum, age) => sum + age, 0) / ages.length;
  const latencyScore = Math.max(0, 100 - (avgLatency / FRESHNESS_THRESHOLD_MS) * 100);
  
  // Combined score (weighted average)
  return (recentPercentage * 0.7 + latencyScore * 0.3);
}

function validateMessageStructure(type, data, message) {
  const errors = [];
  
  // Helper to check if timestamp exists (either in data or message level)
  const hasTimestamp = () => {
    return !!(data.timestamp || message.server_timestamp_ms || message.server_timestamp);
  };
  
  switch (type) {
    case 'agent_state':
      if (!data.state) errors.push('Missing state field');
      if (!hasTimestamp() && !data.last_update) errors.push('Missing timestamp');
      break;
      
    case 'signal_update':
      if (!data.signal) errors.push('Missing signal field');
      if (data.confidence === undefined) errors.push('Missing confidence field');
      if (!hasTimestamp()) errors.push('Missing timestamp');
      break;
      
    case 'reasoning_chain_update':
      if (!data.reasoning_chain) errors.push('Missing reasoning_chain field');
      if (!Array.isArray(data.reasoning_chain)) errors.push('reasoning_chain must be an array');
      if (data.final_confidence === undefined) errors.push('Missing final_confidence field');
      if (!hasTimestamp()) errors.push('Missing timestamp');
      break;
      
    case 'model_prediction_update':
      if (!data.model_consensus) errors.push('Missing model_consensus field');
      if (!Array.isArray(data.model_consensus)) errors.push('model_consensus must be an array');
      if (data.consensus_confidence === undefined) errors.push('Missing consensus_confidence field');
      if (!hasTimestamp()) errors.push('Missing timestamp');
      break;
      
    case 'market_tick':
      if (!data.symbol) errors.push('Missing symbol field');
      if (data.price === undefined) errors.push('Missing price field');
      if (!hasTimestamp()) errors.push('Missing timestamp');
      break;
      
    case 'trade_executed':
      if (!data.trade_id) errors.push('Missing trade_id field');
      if (!data.symbol) errors.push('Missing symbol field');
      if (!hasTimestamp()) errors.push('Missing timestamp');
      break;
      
    case 'portfolio_update':
      if (data.total_value === undefined) errors.push('Missing total_value field');
      // Portfolio updates can use server_timestamp_ms (added by WebSocket manager)
      // So we don't require data.timestamp if server_timestamp_ms exists
      break;
      
    case 'health_update':
      if (!data.status) errors.push('Missing status field');
      if (!hasTimestamp()) errors.push('Missing timestamp');
      break;
      
    case 'time_sync':
      // time_sync messages may not have data.timestamp, they use server_timestamp_ms
      break;
  }
  
  return errors;
}

function checkMessageFreshness(message) {
  // Check if message has server timestamp
  if (message.server_timestamp_ms) {
    const age = Date.now() - message.server_timestamp_ms;
    return age;
  }
  
  // Check data.timestamp if available
  if (message.data?.timestamp) {
    const timestamp = new Date(message.data.timestamp).getTime();
    if (!isNaN(timestamp)) {
      const age = Date.now() - timestamp;
      return age;
    }
  }
  
  return -1;
}

function handleMessage(message) {
  const type = message.type;
  const result = results.get(type);
  
  if (!result) {
    console.warn(`⚠️  Received unexpected message type: ${type}`);
    return;
  }
  
  result.received = true;
  result.messageCount++;
  result.lastReceived = new Date();
  
  // Validate message structure (pass full message for timestamp checking)
  const validationErrors = validateMessageStructure(type, message.data, message);
  result.errors.push(...validationErrors);
  
  // Check message freshness
  const messageAge = checkMessageFreshness(message);
  if (messageAge >= 0) {
    // Store the message age directly (in milliseconds)
    messageTimestamps.get(type).push(messageAge);
    
    // Update freshness score
    const ages = messageTimestamps.get(type);
    result.freshnessScore = calculateFreshnessScore(ages);
    
    // Calculate average latency (use stored ages directly)
    if (ages.length > 0) {
      result.averageLatency = ages.reduce((sum, age) => sum + age, 0) / ages.length;
    }
  } else {
    result.errors.push('Missing or invalid timestamp');
  }
  
  // Log message receipt
  const ageStr = messageAge >= 0 ? `${messageAge.toFixed(0)}ms old` : 'no timestamp';
  console.log(`✅ [${type}] Message #${result.messageCount} received (${ageStr})`);
  
  // Log validation errors if any
  if (validationErrors.length > 0) {
    console.error(`❌ [${type}] Validation errors:`, validationErrors);
  }
}

function printResults() {
  console.log('\n' + '='.repeat(80));
  console.log('📊 TEST RESULTS SUMMARY');
  console.log('='.repeat(80));
  
  let totalReceived = 0;
  let totalMessages = 0;
  let totalErrors = 0;
  
  results.forEach((result, type) => {
    totalReceived += result.received ? 1 : 0;
    totalMessages += result.messageCount;
    totalErrors += result.errors.length;
    
    const status = result.received ? '✅' : '❌';
    const freshness = result.freshnessScore >= 70 ? '🟢' : result.freshnessScore >= 40 ? '🟡' : '🔴';
    
    console.log(`\n${status} ${type}:`);
    console.log(`   Messages received: ${result.messageCount}`);
    console.log(`   Last received: ${result.lastReceived ? result.lastReceived.toISOString() : 'Never'}`);
    if (result.averageLatency !== undefined) {
      console.log(`   Average latency: ${result.averageLatency.toFixed(0)}ms`);
    }
    console.log(`   Freshness score: ${freshness} ${result.freshnessScore.toFixed(1)}/100`);
    if (result.errors.length > 0) {
      console.log(`   ⚠️  Errors: ${result.errors.length}`);
      result.errors.slice(0, 3).forEach(err => console.log(`      - ${err}`));
      if (result.errors.length > 3) {
        console.log(`      ... and ${result.errors.length - 3} more`);
      }
    }
  });
  
  console.log('\n' + '-'.repeat(80));
  console.log('📈 OVERALL STATISTICS');
  console.log('-'.repeat(80));
  console.log(`Total message types: ${expectedMessageTypes.length}`);
  console.log(`Message types received: ${totalReceived}/${expectedMessageTypes.length}`);
  console.log(`Total messages received: ${totalMessages}`);
  console.log(`Total errors: ${totalErrors}`);
  console.log(`Test duration: ${TEST_DURATION_MS / 1000}s`);
  console.log(`Messages per second: ${(totalMessages / (TEST_DURATION_MS / 1000)).toFixed(2)}`);
  
  // Calculate overall freshness
  const avgFreshness = Array.from(results.values())
    .filter(r => r.received)
    .reduce((sum, r) => sum + r.freshnessScore, 0) / (totalReceived || 1);
  console.log(`Average freshness score: ${avgFreshness.toFixed(1)}/100`);
  
  console.log('\n' + '='.repeat(80));
  console.log('🎯 VERIFICATION CHECKLIST');
  console.log('='.repeat(80));
  
  const criticalTypes = ['market_tick', 'agent_state', 'signal_update'];
  let allCriticalPassed = true;
  
  criticalTypes.forEach(type => {
    const result = results.get(type);
    if (result && result.received && result.messageCount > 0) {
      const isFresh = result.freshnessScore >= 70;
      const status = isFresh ? '✅ PASS' : '⚠️  WARN';
      console.log(`${status} ${type}: ${result.messageCount} messages, freshness ${result.freshnessScore.toFixed(1)}%`);
      if (!isFresh) allCriticalPassed = false;
    } else {
      console.log(`❌ FAIL ${type}: No messages received`);
      allCriticalPassed = false;
    }
  });
  
  const newTypes = ['reasoning_chain_update', 'model_prediction_update'];
  console.log('\nNew message types (from implementation):');
  newTypes.forEach(type => {
    const result = results.get(type);
    if (result && result.received && result.messageCount > 0) {
      console.log(`✅ ${type}: ${result.messageCount} messages received`);
    } else {
      console.log(`⚠️  ${type}: No messages received (may be normal if agent not actively reasoning)`);
    }
  });
  
  console.log('\n' + '='.repeat(80));
  
  // Check if agent-related messages are missing (might be normal if agent not active)
  const agentMessagesMissing = !results.get('agent_state')?.received && 
                                !results.get('signal_update')?.received;
  const agentActive = results.get('agent_state')?.received || 
                     results.get('signal_update')?.received ||
                     results.get('reasoning_chain_update')?.received ||
                     results.get('model_prediction_update')?.received;
  
  if (allCriticalPassed && totalReceived >= criticalTypes.length) {
    console.log('✅ TEST PASSED: Realtime data flow is working correctly!');
  } else if (agentMessagesMissing && !agentActive) {
    console.log('⚠️  TEST PARTIAL: Core WebSocket is working, but agent is not actively processing.');
    console.log('   This is normal if the agent is idle. To test agent messages:');
    console.log('   1. Ensure agent is running and actively trading/reasoning');
    console.log('   2. Trigger a prediction or wait for agent to make a decision');
    console.log('   3. Run the test again');
  } else {
    console.log('❌ TEST FAILED: Some critical message types are missing or not fresh');
  }
  console.log('='.repeat(80) + '\n');
}

async function runTest() {
  console.log('🚀 Starting WebSocket Realtime Data Test');
  console.log(`📡 Connecting to: ${WS_URL}`);
  console.log(`⏱️  Test duration: ${TEST_DURATION_MS / 1000} seconds`);
  console.log(`🎯 Freshness threshold: ${FRESHNESS_THRESHOLD_MS}ms\n`);
  
  return new Promise((resolve, reject) => {
    try {
      ws = new WebSocket(WS_URL);
      
      ws.on('open', () => {
        console.log('✅ WebSocket connected successfully\n');
        console.log('📥 Listening for messages...\n');
        
        // Set test end timer
        setTimeout(() => {
          isRunning = false;
          if (ws) {
            ws.close();
          }
          printResults();
          resolve();
        }, TEST_DURATION_MS);
      });
      
      ws.on('message', (data) => {
        try {
          const message = JSON.parse(data.toString());
          handleMessage(message);
        } catch (error) {
          console.error('❌ Error parsing message:', error);
        }
      });
      
      ws.on('error', (error) => {
        console.error('❌ WebSocket error:', error);
        reject(error);
      });
      
      ws.on('close', () => {
        console.log('\n🔌 WebSocket connection closed');
        if (isRunning) {
          console.log('⚠️  Connection closed before test completion');
          printResults();
        }
        resolve();
      });
      
    } catch (error) {
      console.error('❌ Failed to create WebSocket connection:', error);
      reject(error);
    }
  });
}

// Run the test
runTest()
  .then(() => {
    console.log('✅ Test completed');
    process.exit(0);
  })
  .catch((error) => {
    console.error('❌ Test failed:', error);
    process.exit(1);
  });
