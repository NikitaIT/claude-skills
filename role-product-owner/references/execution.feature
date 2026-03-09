Feature: Sprint execution

  Background:
    Given the Product Backlog is ordered and top items have approach status

  Scenario: Always publish repository changes
    Given any changes are made to the repository
    When DoD is met
    Then commit and push them
  # --- Sprint Planning (SG: "initiates the Sprint by laying out the work") ---
  Rule: Topic One — Why is this Sprint valuable?

    Scenario: PO proposes Sprint value
      Given the previous Sprint ended or this is the first Sprint
      When Sprint Planning begins
      Then run `uv run python product/board.py forecast` to inspect past performance
      And propose a Sprint Goal that communicates why this Sprint is valuable
      And report the forecast and goal to the stakeholder

  Rule: Topic Two — What can be Done this Sprint?

    Scenario: Select PBIs for the Sprint
      Given the stakeholder approved the Sprint Goal
      When the PO selects items for the Sprint
      Then pick from the Product Backlog (bugs first, then features)
      And if a PBI approach has multiple independent parts — refine it into smaller items
      And no hard limit on count — past performance and batched execution inform the forecast

    Scenario: Start the Sprint
      Given PBIs are selected
      When the Sprint Backlog is formed
      Then start a sprint: `uv run python product/board.py sprint start "<goal>"`
      And commit and push sprint start

  Rule: Topic Three — How will the chosen work get done? (Developers' sole discretion)

    Scenario: Pre-spawn gates
      Given a sprint is started
      When preparing to spawn agents
      Then verify git status is clean — commit and push if needed
      And run: uv run python product/board.py sprint check
      And do NOT spawn agents until all checks pass

    Scenario: Spawn developer agents (batch of up to 5)
      Given all gates passed
      When agents are ready to be spawned
      Then run: scripts/worktree-pool.sh init
      And take the next batch of up to 5 unstarted PBIs from the sprint
      And assign one worktree (dev-1..dev-5) per PBI
      And generate prompt: uv run python product/board.py agent-prompt <pbi_id> <dev-N>
      And spawn one Agent (subagent_type=general-purpose) per PBI with run_in_background=true
      But do NOT use isolation="worktree" — agents use pre-created worktrees

    Scenario: Spawn next batch when worktrees free up
      Given a batch finished and unstarted PBIs remain in the sprint
      When a worktree becomes available
      Then pull changes: git pull --rebase origin main
      And assign freed worktrees to next PBIs and spawn agents

    # --- During the Sprint (SG: "The Product Backlog is refined as needed") ---

  Rule: PO refines backlog while Developers work

    Scenario: Refine while agents work
      Given agents are running in background
      When the PO has idle time
      Then continue refining: remaining backlog, DoR, PBI updates
      And before committing, clean agent worktree artifacts from working tree
      And commit and push PO changes independently

  Rule: Inspect progress toward the Sprint Goal

    Scenario: Log metrics when agent finishes
      Given a developer agent is running
      When the agent completes
      Then extract from <usage> tag: duration_ms, total_tokens, tool_uses, status
      And append a row to product/agent_log.csv
      And report: which PBI is done, test count, agent cost

    Scenario: Agent fails
      Given a developer agent is running
      When the agent reports failure
      Then read the agent output to understand the error
      And decide: resume the agent or spawn a new one
      And if merge conflict — pull main first then retry
      But never close the sprint with failed PBIs — move them back or fix

    # --- Sprint Review (SG: "inspect the outcome and determine future adaptations") ---

  Rule: Present the Increment to stakeholders

    Scenario: Close sprint and review
      Given all PBIs in the sprint are done
      When the last batch finishes
      Then pull all changes: git pull --rebase origin main
      And verify: cat product/sprint_backlog.csv should be empty
      And end the sprint: `uv run python product/board.py sprint end`
      And push (pre-push hook runs pnpm check automatically)

    # --- Sprint Retrospective (SG: "plan ways to increase quality and effectiveness") ---

  Rule: Identify the most impactful improvement

    Scenario: Sprint retrospective
      Given the sprint just ended and agent_log has metrics
      When the Sprint Review is complete
      Then run `uv run python product/board.py retro`
      And identify ONE most impactful improvement for next sprint
      And if process change — update PO or Dev role
      And if code change — create a [process] PBI in the backlog

    # --- Continuity (SG: "A new Sprint starts immediately after the previous") ---

  Rule: Sprints are continuous

    Scenario: Start next sprint immediately
      Given the backlog is not empty
      When the Sprint Retrospective completed
      Then immediately start the next Sprint Planning
      And keep going until the backlog is empty or the stakeholder says stop
