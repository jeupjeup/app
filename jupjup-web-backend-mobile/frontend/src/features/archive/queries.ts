import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuthenticatedUserId, useSessionScope } from '@/shared/auth/session'
import { getContent, getJob, listContents, type ListParams } from '@/shared/api/contents'
import { getCollection, listCollections } from '@/shared/api/collections'
import { isAlias } from '@/shared/api/contracts'
export const activeJob = (status?: string) => ['queued', 'running', 'retry_wait', 'awaiting_confirmation'].includes(status || '')
export function useContents(params: ListParams = {}) {
  const userId = useAuthenticatedUserId()
  const scope = useSessionScope()
  return useInfiniteQuery({
    enabled: !!userId, refetchOnWindowFocus: true,
    queryKey: ['contents', scope, params], initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => listContents({ ...params, cursor: pageParam }, signal),
    refetchInterval: query => query.state.data?.pages.some(page => page.items.some(item => item.status === 'pending')) ? 2000 : 15000,
    getNextPageParam: page => page.has_more ? page.next_cursor || undefined : undefined,
  })
}
export function useContent(id: string) {
  const scope = useSessionScope()
  return useQuery({ queryKey: ['content', scope, id], queryFn: ({ signal }) => getContent(id, signal), enabled: !!id,
    refetchOnWindowFocus: true,
    refetchInterval: query => {
      const data = query.state.data?.data
      return data && !isAlias(data) && data.status === 'pending' ? 2000 : false
    },
  })
}
export const jobPollInterval = (status?: string, hasError = false) => hasError || !status || activeJob(status) ? 2000 : false
export function useJob(id: string | null | undefined) {
  const scope = useSessionScope()
  return useQuery({ queryKey: ['job', scope, id], queryFn: ({ signal }) => getJob(id!, signal), enabled: !!id, staleTime: 0,
    retry: 1, refetchOnWindowFocus: true,
    refetchInterval: query => jobPollInterval(query.state.data?.status, !!query.state.error),
  })
}
export function useRefreshArchive() {
  const scope = useSessionScope()
  const client = useQueryClient()
  return async () => { await Promise.all(['contents', 'content', 'collections', 'collection', 'search', 'job'].map(key => client.invalidateQueries({ queryKey: [key, scope] }))) }
}

export function useCollections() {
  const userId = useAuthenticatedUserId()
  const scope = useSessionScope()
  return useQuery({ enabled: !!userId, refetchOnWindowFocus: true, queryKey: ['collections', scope], queryFn: ({ signal }) => listCollections(signal) })
}
export function useCollection(id: string) {
  const scope = useSessionScope()
  return useQuery({ queryKey: ['collection', scope, id], queryFn: ({ signal }) => getCollection(id, signal), enabled: !!id, retry: 1 })
}
