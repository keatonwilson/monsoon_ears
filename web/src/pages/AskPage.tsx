// Ask — NL→SQL over the events store (dashboard/tabs/query.py).
//
// Mutation-only: no polling is registered on this route, so nothing can
// disturb the textarea while the user is composing a question.

import { useState } from 'react'
import { Loader2, Sparkles } from 'lucide-react'

import { useNlQuery } from '@/api/queries'
import { ApiError } from '@/api/client'
import { ErrorState } from '@/components/ErrorState'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'

const SUGGESTIONS = [
  'Show me the last 10 EMS dispatches',
  'Which APRS stations reported rainfall in the last hour?',
  'Count events by transmission_type in the last 24 hours',
  'List monsoon-digest alerts from this week',
]

function ResultsTable({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = Object.keys(rows[0] ?? {})
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {columns.map((col) => (
            <TableHead key={col}>{col}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, i) => (
          <TableRow key={i}>
            {columns.map((col) => (
              <TableCell key={col} className="max-w-xs truncate text-xs" title={String(row[col] ?? '')}>
                {row[col] == null ? '—' : String(row[col])}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export default function AskPage() {
  const [question, setQuestion] = useState('')
  const query = useNlQuery()

  const canRun = question.trim().length >= 3 && !query.isPending
  const run = () => {
    if (canRun) query.mutate(question.trim())
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">Ask Monsoon Ears</h1>
        <p className="text-sm text-muted-foreground">
          Plain-English questions about the events store. Haiku rewrites your question into a
          SELECT; the API rejects anything that isn't a single read-only query over the allowed
          tables.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setQuestion(s)}
            className="rounded-full border px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            {s}
          </button>
        ))}
      </div>

      <Textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) run()
        }}
        placeholder="e.g. show me cardiac calls in the last 24 hours"
        maxLength={500}
        rows={3}
      />

      <Button onClick={run} disabled={!canRun}>
        {query.isPending ? (
          <>
            <Loader2 className="size-4 animate-spin" /> Asking Haiku…
          </>
        ) : (
          <>
            <Sparkles className="size-4" /> Run query
          </>
        )}
      </Button>

      {query.isError && (
        <ErrorState
          title={query.error instanceof ApiError && query.error.status === 400 ? 'Query rejected' : 'API error'}
          error={query.error}
        />
      )}

      {query.data && (
        <div className="space-y-3">
          <div>
            <p className="text-sm font-medium">Generated SQL</p>
            <pre className="overflow-x-auto rounded-lg border bg-muted/40 p-3 text-xs">
              <code>{query.data.sql}</code>
            </pre>
          </div>
          {query.data.row_count === 0 ? (
            <p className="text-sm text-muted-foreground">
              Query ran successfully but returned no rows.
            </p>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">
                {query.data.row_count} row{query.data.row_count === 1 ? '' : 's'}
              </p>
              <ResultsTable rows={query.data.rows} />
            </>
          )}
        </div>
      )}
    </div>
  )
}
